"""Tool registry for dynamic tool management."""

from __future__ import annotations
from typing import Any, TYPE_CHECKING

from nanobot.agent.tools.base import Tool
from nanobot.config.loader import load_config

from loguru import logger
import weakref

if TYPE_CHECKING:
    pass 

_active_registry: ToolRegistry | None = None


def get_active_registry() -> ToolRegistry | None:
    """Return the most-recently created ToolRegistry, or None."""
    return _active_registry

class ToolRegistry:
    """
    Registry for agent tools.

    Allows dynamic registration and execution of tools.
    """

    _instances: weakref.WeakSet['ToolRegistry'] = weakref.WeakSet()
    _DEFERRED_ONLY_TOOLS: frozenset[str] = frozenset({"tool_loader"})
    def __init__(self, semantic_deferred_tools_enabled: bool = False):
        ToolRegistry._instances.add(self)
        
        self._tools: dict[str, Tool] = {}
        self._cached_definitions: list[dict[str, Any]] | None = None
        
        config = load_config().context
        self._semantic_deferred_tools_enabled = config.deferred_toggle
        self._embedding_store = None

        # Names of tools that are currently "loaded" (full schema sent to LLM).
        # Populated in register() based on each tool's _default_deferred +
        # any persisted user overrides.
        self._loaded_tool_names: set[str] = set()

        # Load persisted per-tool deferred overrides from disk.  Done once at
        # construction time; live updates arrive via set_tool_deferred().
        self._deferred_overrides: dict[str, bool] = self._load_overrides()

        if self._semantic_deferred_tools_enabled:
            from .embeddings import ToolEmbeddingStore
            self._embedding_store = ToolEmbeddingStore()

        # Register this instance as the process-wide active registry so the
        # settings API — and ToolLoaderTool.create() — can reach it without a
        # direct import cycle.  Must happen before ToolLoader runs.
        global _active_registry
        _active_registry = self
        
        logger.info("init")
        logger.info(self._semantic_deferred_tools_enabled)

    def reload(self, new_deferred_toggle: bool | None = None) -> bool:
        """Broadcast the deferred_toggle update to ALL active registries."""
        new_value = (
            new_deferred_toggle
            if new_deferred_toggle is not None
            else load_config().context.deferred_toggle
        )
        
        changed_any = False
        # list() creates a safe snapshot to iterate over
        for instance in list(ToolRegistry._instances):
            if instance._reload_instance(new_value):
                changed_any = True
        return changed_any

    def _reload_instance(self, new_value: bool) -> bool:
        """Internal reload logic for a specific instance."""
        if new_value == self._semantic_deferred_tools_enabled:
            return False  # nothing changed, skip work

        self._semantic_deferred_tools_enabled = new_value
        self._cached_definitions = None  # force rebuild on next get_definitions()

        if new_value:
            # Feature enabled: spin up the embedding store.
            from .embeddings import ToolEmbeddingStore
            self._embedding_store = ToolEmbeddingStore()
        else:
            # Feature disabled: release the embedding store.
            self._embedding_store = None

        return True
    
    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_overrides() -> dict[str, bool]:
        """Read persisted deferred overrides, returning {} on any error."""
        try:
            from nanobot.webui.tool_states import read_deferred_overrides
            return read_deferred_overrides()
        except Exception:  # pragma: no cover
            return {}

    @staticmethod
    def _persist_overrides(overrides: dict[str, bool]) -> None:
        """Write the full overrides dict to disk, ignoring errors."""
        try:
            from nanobot.webui.tool_states import write_tool_states
            write_tool_states(overrides)
        except Exception:  # pragma: no cover
            pass
            
    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _effective_deferred(self, tool: Tool) -> bool:
        """Return True if *tool* should start in the deferred (not-loaded) state.

        Priority: user override > tool's ``_default_deferred`` class attr > True.
        """
        name = tool.name
        if name in self._deferred_overrides:
            return self._deferred_overrides[name]
        return bool(getattr(tool, "_default_deferred", True))

    def _apply_loaded_state(self, tool: Tool) -> None:
        """Mark *tool* as loaded or deferred based on effective state."""
        if not self._effective_deferred(tool):
            self._loaded_tool_names.add(tool.name)
        else:
            self._loaded_tool_names.discard(tool.name)

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, tool: Tool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool
        self._cached_definitions = None
        self._apply_loaded_state(tool)

    def unregister(self, name: str) -> None:
        """Unregister a tool by name."""
        self._tools.pop(name, None)
        self._loaded_tool_names.discard(name)
        self._cached_definitions = None
        
        if self._embedding_store:
            self._embedding_store.remove_tool(name)

    # ------------------------------------------------------------------
    # Loaded / deferred state
    # ------------------------------------------------------------------

    def mark_loaded(self, name: str) -> None:
        """Promote *name* from deferred to loaded.

        On the next call to :meth:`get_definitions` the tool will be included
        with its full OpenAI schema and will no longer appear in the deferred
        list returned by :meth:`build_deferred_tools_summary`.

        Safe to call repeatedly — subsequent calls for the same name are no-ops.
        """
        if name not in self._loaded_tool_names:
            self._loaded_tool_names.add(name)
            self._cached_definitions = None

    def is_loaded(self, name: str) -> bool:
        """Return True if *name* is in the loaded (fully-schema'd) tool set."""
        if not self._semantic_deferred_tools_enabled:
            return True
        return name in self._loaded_tool_names

    def set_tool_deferred(self, name: str, deferred: bool | None) -> None:
        """Set or clear the deferred override for *name* and persist.

        Args:
            name:     Tool name (must be registered).
            deferred: ``True`` → force-defer, ``False`` → force-load,
                      ``None`` → remove override (revert to tool default).

        This updates both the in-memory state and the on-disk override file.
        The change takes effect immediately for :meth:`get_definitions` and
        :meth:`build_deferred_tools_summary`.
        """
        if deferred is None:
            self._deferred_overrides.pop(name, None)
        else:
            self._deferred_overrides[name] = deferred
            
        # Sync in-memory loaded/deferred state.
        tool = self._tools.get(name)
        if tool is not None:
            self._apply_loaded_state(tool)
            self._cached_definitions = None

        self._persist_overrides(self._deferred_overrides)

    def get_all_tool_states(self) -> list[dict[str, Any]]:
        """Return a list of tool-state dicts suitable for the settings payload.

        Each entry contains:
        - ``name``: tool name
        - ``description``: first sentence of tool description
        - ``default_deferred``: the tool class's declared default
        - ``deferred``: current effective deferred state (override > default)
        - ``has_override``: whether a user override exists
        """
        states: list[dict[str, Any]] = []
        for name in sorted(self._tools):
            tool = self._tools[name]
            default_deferred = bool(getattr(tool, "_default_deferred", True))
            has_override = name in self._deferred_overrides
            effective_deferred = (
                self._deferred_overrides[name] if has_override else default_deferred
            )
            states.append(
                {
                    "name": name,
                    "description": self._brief_description(tool),
                    "default_deferred": default_deferred,
                    "deferred": effective_deferred,
                    "has_override": has_override,
                }
            )
        return states

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------            

    def get(self, name: str) -> Tool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools

    @staticmethod
    def _schema_name(schema: dict[str, Any]) -> str:
        """Extract a normalized tool name from either OpenAI or flat schemas."""
        fn = schema.get("function")
        if isinstance(fn, dict):
            name = fn.get("name")
            if isinstance(name, str):
                return name
        name = schema.get("name")
        return name if isinstance(name, str) else ""

    def get_definitions(self) -> list[dict[str, Any]]:
        """Return full OpenAI schemas **only** for currently-loaded tools.

        Deferred tools are handled by :meth:`build_deferred_tools_summary` and
        injected into the system message by
        :class:`~nanobot.agent.context.ContextBuilder` — those tools do **not**
        appear in the OpenAI ``tools`` array until the model calls
        ``tool_loader``.
        """
        if self._cached_definitions is not None:
            return self._cached_definitions

        if self._semantic_deferred_tools_enabled:
            loaded_tools = [
                tool for name, tool in self._tools.items()
                if name in self._loaded_tool_names
            ]
        else:
            loaded_tools = [
                tool for name, tool in self._tools.items()
                if name not in self._DEFERRED_ONLY_TOOLS
            ]

        definitions = [tool.to_schema() for tool in loaded_tools]
        builtins: list[dict[str, Any]] = []
        mcp_tools: list[dict[str, Any]] = []
        for schema in definitions:
            name = self._schema_name(schema)
            if name.startswith("mcp_"):
                mcp_tools.append(schema)
            else:
                builtins.append(schema)

        builtins.sort(key=self._schema_name)
        mcp_tools.sort(key=self._schema_name)
        self._cached_definitions = builtins + mcp_tools
        return self._cached_definitions
        
     # ------------------------------------------------------------------
    # Deferred-tool summary — consumed by ContextBuilder
    # ------------------------------------------------------------------

    def build_deferred_tools_summary(self, query: str | None = None) -> str:
        """Return a bullet-list of deferred tools for system-prompt injection.

        Analogous to :meth:`~nanobot.agent.skills.SkillsLoader.build_skills_summary`.
        Returns a formatted Markdown list *without* a section header so the
        caller (:class:`~nanobot.agent.context.ContextBuilder`) can embed it
        inside whatever heading structure fits the system prompt.

        When *query* is provided and the embedding model is available, tools are
        ordered by cosine similarity (descending) and their relevance scores are
        shown so the LLM can prioritise the most relevant ones.  Falls back to
        alphabetical order with one-line descriptions when the model is
        unavailable or no query is given.

        Returns an empty string when there are no deferred tools or when the
        deferred-loading feature is disabled.
        """
        if not self._semantic_deferred_tools_enabled:
            return ""

        deferred_names: set[str] = {
            name for name in self._tools if name not in self._loaded_tool_names
        }
        if not deferred_names:
            return ""

        # Bulk-encode all tools (cheap no-op for already-cached entries) so the
        # embedding store is fresh before we score against *query*.
        if query is not None and self._embedding_store is not None:
            self._embedding_store.bulk_index(list(self._tools.values()))

        lines: list[str] = []

        if (
            query is not None
            and self._embedding_store is not None
            and self._embedding_store.indexed_count() > 0
        ):
            # Semantic mode: order by relevance, show scores.
            scored = self._embedding_store.all_with_scores(
                query, exclude=self._loaded_tool_names
            )
            for entry in scored:
                tool_name = entry["name"]
                if tool_name not in deferred_names:
                    continue
                tool = self._tools[tool_name]
                try:
                    score = float(entry["description"].split()[-1])
                except (ValueError, IndexError):
                    score = 0.0
                brief = self._brief_description(tool)
                suffix = f" — {brief}" if brief else ""
                lines.append(f"- **{tool_name}**{suffix}  (relevance: {score:.4f})")
        else:
            # Fallback: alphabetical with one-line description.
            for name in sorted(deferred_names):
                tool = self._tools[name]
                brief = self._brief_description(tool)
                suffix = f" — {brief}" if brief else ""
                lines.append(f"- **{name}**{suffix}")

        return "\n".join(lines) 

    @staticmethod
    def _brief_description(tool: Tool) -> str:
        """Return the first sentence of *tool.description*, stripped."""
        desc = getattr(tool, "description", "") or ""
        for sep in (".", "\n"):
            idx = desc.find(sep)
            if idx != -1:
                desc = desc[:idx]
                break
        return desc.strip()

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------        

    def prepare_call(
        self,
        name: str,
        params: dict[str, Any],
    ) -> tuple[Tool | None, dict[str, Any], str | None]:
        """Resolve, cast, and validate one tool call."""
        # Guard against invalid parameter types (e.g., list instead of dict)
        if not isinstance(params, dict) and name in ('write_file', 'read_file'):
            return None, params, (
                f"Error: Tool '{name}' parameters must be a JSON object, got {type(params).__name__}. "
                "Use named parameters: tool_name(param1=\"value1\", param2=\"value2\")"
            )

        tool = self._tools.get(name)
        if not tool:
            if self._semantic_deferred_tools_enabled and name in {t for t in self._tools if t not in self._loaded_tool_names}:
                return None, params, (
                    f"Error: Tool '{name}' is deferred and not yet loaded. "
                    f"Call tool_loader(tool_name=\"{name}\") first to get its full schema."
                )
            return None, params, (
                f"Error: Tool '{name}' not found. Available: {', '.join(self.tool_names)}"
            )

        cast_params = tool.cast_params(params)
        errors = tool.validate_params(cast_params)
        if errors:
            return tool, cast_params, (
                f"Error: Invalid parameters for tool '{name}': " + "; ".join(errors)
            )
        return tool, cast_params, None

    async def execute(self, name: str, params: dict[str, Any]) -> Any:
        """Execute a tool by name with given parameters."""
        _HINT = "\n\n[Analyze the error above and try a different approach.]"
        tool, params, error = self.prepare_call(name, params)
        if error:
            return error + _HINT

        try:
            assert tool is not None  # guarded by prepare_call()
            result = await tool.execute(**params)
            if isinstance(result, str) and result.startswith("Error"):
                return result + _HINT
            return result
        except Exception as e:
            return f"Error executing {name}: {str(e)}" + _HINT

    @property
    def tool_names(self) -> list[str]:
        """Get list of registered tool names."""
        if self._semantic_deferred_tools_enabled:
            return list(self._loaded_tool_names)
        return [name for name in self._tools if name not in self._DEFERRED_ONLY_TOOLS]

    @property
    def loaded_tool_names(self) -> list[str]:
        """Names of tools currently in the fully-loaded (OpenAI schema) set."""
        return sorted(self._loaded_tool_names & self._tools.keys())

    @property
    def deferred_tool_names(self) -> list[str]:
        """Names of tools that are registered but not yet loaded."""
        if not self._semantic_deferred_tools_enabled:
            return []
        return sorted(n for n in self._tools if n not in self._loaded_tool_names)

    def __len__(self) -> int:
        if self._semantic_deferred_tools_enabled:
            return len(self._loaded_tool_names)
        return sum(1 for name in self._tools if name not in self._DEFERRED_ONLY_TOOLS)

    def __contains__(self, name: str) -> bool:
        if self._semantic_deferred_tools_enabled:
            return name in self._loaded_tool_names
        return name in self._tools and name not in self._DEFERRED_ONLY_TOOLS
