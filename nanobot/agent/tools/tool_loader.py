"""Tool loader — lets the LLM fetch full schemas for deferred tools at runtime.

This tool must always be fully loaded (never deferred) so the model can always
call it.  Its ``_default_deferred = False`` class attribute ensures it starts
in the loaded set without any special-casing in the registry.

It is discovered and registered exactly like every other tool.  The only
difference is that its :meth:`create` classmethod resolves the active registry
via :func:`~nanobot.agent.tools.registry.get_active_registry` rather than
relying on the default zero-argument ``cls()`` constructor, since the registry
reference must be injected at creation time.

Usage by the LLM
----------------
When the system context lists deferred tools, the model should call::

    tool_loader(tool_name="<name>")

before attempting to invoke the deferred tool.  The response is the full
OpenAI function-call JSON for that tool.  The runner will also automatically
promote the tool to the *loaded* list so it appears as a first-class entry in
the OpenAI tools array on the very next iteration — the model does not need to
parse the JSON manually, it is there as a fallback.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, ClassVar

from nanobot.agent.tools.base import Tool, tool_parameters

if TYPE_CHECKING:
    from nanobot.agent.tools.registry import ToolRegistry


@tool_parameters({
    "type": "object",
    "properties": {
        "tool_names": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "description": (
                "One or more exact tool names whose full schemas you want to load. "
                "Use names exactly as listed in the 'Deferred Tools' section of the "
                "system context. Pass multiple names to load several tools in a single "
                "call rather than calling tool_loader repeatedly."
            ),
        },
    },
    "required": ["tool_names"],
})
class ToolLoaderTool(Tool):
    """Loads the full parameter schema for one or more deferred tools and promotes them to active.

    After a successful call each named tool is permanently promoted to the
    *loaded* list: from the next LLM iteration onwards it will appear in the
    OpenAI tools array with its real parameter schema, so the model can invoke
    it directly without calling tool_loader again.

    Multiple tools may be requested in a single call by passing a list of
    names, which avoids a round-trip per tool when several deferred tools are
    needed at once.
    """

    # ------------------------------------------------------------------
    # Class-level attributes
    # ------------------------------------------------------------------

    #: Always fully loaded — the model must always be able to call tool_loader
    #: regardless of the user's per-tool deferred settings.
    _default_deferred: ClassVar[bool] = False

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def create(cls, ctx: Any) -> "ToolLoaderTool":
        # No registry capture here — resolved lazily in execute()
        return cls()

    # ------------------------------------------------------------------
    # Constructor
    # ------------------------------------------------------------------

    def __init__(self, registry: ToolRegistry | None = None) -> None:
        """
        Args:
            registry: The owning :class:`~nanobot.agent.tools.registry.ToolRegistry`.
                      ``None`` is accepted as a safe default so that import-time
                      introspection (e.g. reading class attributes) does not
                      raise; however ``execute()`` will fail if registry is None.
        """
        self._registry = registry

    # --- Tool identity ---

    @property
    def name(self) -> str:
        return "tool_loader"

    @property
    def description(self) -> str:
        return (
            "Load the full parameter schema for one or more deferred tools so you can call them. "
            "Deferred tools are listed under 'Deferred Tools' in the system context "
            "with their relevance scores. "
            "Call this tool first with the tool_names before attempting to use any "
            "Pass a list of tool names to load several tools at once instead of "
            "calling tool_loader once per tool — it is a no-op for tools that are already loaded."
        )

    # --- Concurrency hints ---

    @property
    def read_only(self) -> bool:
        # Marks as loaded which mutates registry state, but that mutation is
        # idempotent and safe to run alongside other read-only tools.
        return True

    # --- Execution ---

    async def execute(self, tool_names: list[str], **_: Any) -> str:
        registry = self._registry
        if registry is None:
            from nanobot.agent.tools.registry import get_active_registry
            registry = get_active_registry()

        if registry is None:
            return (
                "Error: tool_loader has no registry reference and get_active_registry() "
                "returned None. Ensure a ToolRegistry is created before this tool runs."
            )

        results: list[str] = []
        for tool_name in tool_names:
            tool = registry.get(tool_name)
            if tool is None:
                known = ", ".join(sorted(registry.tool_names))
                results.append(
                    f"Error: Tool '{tool_name}' not found in the registry. "
                    f"Known tools: {known}"
                )
                continue

            registry.mark_loaded(tool_name)
            schema = tool.to_schema()
            results.append(
                f"Tool '{tool_name}' is now loaded. Full schema:\n\n"
                + json.dumps(schema, indent=2)
            )

        return "\n\n---\n\n".join(results)