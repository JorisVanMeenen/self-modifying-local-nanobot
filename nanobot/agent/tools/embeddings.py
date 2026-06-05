"""Semantic embedding store for tool similarity search.

Uses ``sentence-transformers/all-MiniLM-L6-v2`` (384-dim, runs locally) to
encode tool definitions and rank them against a natural-language user query.

The model is loaded lazily on first use so startup time is unaffected for
workloads that never trigger a search.  Embeddings are persisted to disk and
reloaded on startup; each entry is keyed by a SHA-256 hash of the tool's text
representation so only changed tools are re-encoded.

Install the optional dependency:
    pip install sentence-transformers   # ≈ 100 MB with model weights

If the package is absent the store degrades gracefully: all search calls
return an empty list and the tool-search feature becomes a no-op.
"""

from __future__ import annotations

import hashlib
import logging
import pickle
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# numpy is a transitive dependency of sentence-transformers; if the model
# loads successfully, numpy is already present.  Import once here so neither
# index_tool() nor search() need repeated try/import blocks.
try:
    import numpy as np
    _NUMPY_AVAILABLE = True
except ImportError:  # pragma: no cover
    np = None  # type: ignore[assignment]
    _NUMPY_AVAILABLE = False

# Sentinel flags so we attempt the heavyweight import only once.
_IMPORT_FAILED: bool = False
_st_model: Any = None  # SentenceTransformer singleton

_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


def _load_model() -> Any:
    """Return the SentenceTransformer singleton, or None if unavailable."""
    global _IMPORT_FAILED, _st_model  # noqa: PLW0603
    if _IMPORT_FAILED:
        return None
    if _st_model is not None:
        return _st_model
    if not _NUMPY_AVAILABLE:
        _IMPORT_FAILED = True
        logger.warning("numpy not available — tool-search similarity disabled.")
        return None
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]

        logger.info("Loading sentence-transformer model '%s' …", _MODEL_NAME)
        try:
            _st_model = SentenceTransformer(_MODEL_NAME, local_files_only=True)
        except Exception:
            logger.info("Weights not found locally. Downloading from Hugging Face...")
            _st_model = SentenceTransformer(_MODEL_NAME, local_files_only=False)
        logger.info("Sentence-transformer model loaded.")
    except Exception as exc:  # noqa: BLE001
        _IMPORT_FAILED = True
        logger.warning(
            "sentence-transformers not available — tool-search similarity disabled. "
            "Install with: pip install sentence-transformers\n"
            "Error: %s",
            exc,
        )
    return _st_model


def _tool_to_text(tool: Any) -> str:
    """Flatten a Tool instance to a single searchable string.

    Combines the tool name, description, and all parameter descriptions so
    the embedding captures the full semantic footprint of the tool.
    Type information is intentionally omitted — it adds noise without
    improving retrieval quality for natural-language queries.
    """
    parts: list[str] = [
        f"Tool: {tool.name}",
        f"Description: {tool.description}",
    ]
    try:
        props: dict[str, Any] = (tool.parameters or {}).get("properties", {})
        if props:
            param_parts: list[str] = []
            for param_name, param_info in props.items():
                if not isinstance(param_info, dict):
                    continue
                desc = param_info.get("description", "")
                enum_vals = param_info.get("enum")
                extra = f" (one of: {enum_vals})" if enum_vals else ""
                param_parts.append(f"{param_name}{extra}: {desc}")
            if param_parts:
                parts.append("Parameters: " + "; ".join(param_parts))
    except Exception:  # noqa: BLE001
        pass
    return "\n".join(parts)


def _text_hash(text: str) -> str:
    """Return a short SHA-256 hex digest of *text* for change detection."""
    return hashlib.sha256(text.encode()).hexdigest()


class ToolEmbeddingStore:
    """Persistent vector store for tool definitions.

    Embeddings are written to a local cache file (pickle) after every mutation
    so they survive process restarts. On load, each entry's hash is compared
    to the live tool text; only stale or new tools are re-encoded.

    Thread-safety: designed for single-threaded async use inside nanobot's
    event loop.  Concurrent writes from multiple threads are not supported.
    """

    def __init__(self) -> None:
        # name -> numpy array of shape (384,)
        self._embeddings: dict[str, Any] = {}
        # name -> plain-text representation used for indexing
        self._texts: dict[str, str] = {}
        # name -> SHA-256 of the text at index time
        self._hashes: dict[str, str] = {}
        
        # Hardcode cache path local to the Linux home directory
        self._cache_path = Path.home() / ".cache" / "nanobot" / "tool_embeddings" / "embeddings_cache.pkl"
        
        self._load_cache()

    # ------------------------------------------------------------------
    # Cache persistence
    # ------------------------------------------------------------------

    def _load_cache(self) -> None:
        """Populate in-memory state from the on-disk pickle, if it exists."""
        if not self._cache_path.exists():
            return
        try:
            with open(self._cache_path, "rb") as fh:
                data = pickle.load(fh)
            self._embeddings = data.get("embeddings", {})
            self._texts = data.get("texts", {})
            self._hashes = data.get("hashes", {})
            logger.info(
                "Loaded %d tool embeddings from cache: %s",
                len(self._embeddings),
                self._cache_path,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load embedding cache (%s): %s", self._cache_path, exc)
            self._embeddings = {}
            self._texts = {}
            self._hashes = {}

    def _save_cache(self) -> None:
        """Atomically write the current state to disk."""
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._cache_path.with_suffix(".tmp")
            with open(tmp, "wb") as fh:
                pickle.dump(
                    {
                        "embeddings": self._embeddings,
                        "texts": self._texts,
                        "hashes": self._hashes,
                    },
                    fh,
                )
            tmp.replace(self._cache_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to save embedding cache (%s): %s", self._cache_path, exc)

    # ------------------------------------------------------------------
    # Index management
    # ------------------------------------------------------------------

    def bulk_index(self, tools: list[Any]) -> None:
        """Encode all *tools* in a single model batch.

        Dramatically faster than calling :meth:`index_tool` in a loop —
        sentence-transformers can encode 50 tools all-at-once 10–20× faster
        than one-by-one due to GPU/CPU batching.  Only tools whose text
        representation has changed (or is new) are re-encoded; the rest are
        kept from the existing cache.

        Saves the cache once after all updates rather than once per tool.
        """
        model = _load_model()
        if model is None or not _NUMPY_AVAILABLE:
            return

        # Compute texts and filter to those that actually need re-encoding.
        to_encode: list[tuple[str, str]] = []  # [(name, text), ...]
        for tool in tools:
            try:
                text = _tool_to_text(tool)
            except Exception as exc:  # noqa: BLE001
                logger.debug("_tool_to_text failed for '%s': %s", tool.name, exc)
                continue
            h = _text_hash(text)
            if self._hashes.get(tool.name) == h:
                continue  # already up-to-date in cache
            to_encode.append((tool.name, text))

        if not to_encode:
            logger.debug("bulk_index: all %d tools already up-to-date.", len(tools))
            return

        try:
            names, texts = zip(*to_encode)
            embeddings = model.encode(
                list(texts),
                convert_to_numpy=True,
                normalize_embeddings=True,
                batch_size=64,
                show_progress_bar=False,
            )
            for name, text, emb in zip(names, texts, embeddings):
                self._embeddings[name] = emb
                self._texts[name] = text
                self._hashes[name] = _text_hash(text)
            logger.info(
                "bulk_index: encoded %d tool(s) (%d unchanged).",
                len(to_encode),
                len(tools) - len(to_encode),
            )
            self._save_cache()
        except Exception as exc:  # noqa: BLE001
            logger.debug("bulk_index encode failed: %s", exc)

    def index_tool(self, tool: Any) -> None:
        """Encode a single *tool* and add it to the store.

        Prefer :meth:`bulk_index` for initial load.  This method is suited
        for incremental updates when a single tool is registered or updated
        after the initial batch.  Skips encoding if the tool text is
        unchanged since the last index.
        """
        model = _load_model()
        if model is None or not _NUMPY_AVAILABLE:
            return
        try:
            text = _tool_to_text(tool)
            h = _text_hash(text)
            if self._hashes.get(tool.name) == h:
                return  # already up-to-date
            emb = model.encode(text, convert_to_numpy=True, normalize_embeddings=True)
            self._embeddings[tool.name] = emb
            self._texts[tool.name] = text
            self._hashes[tool.name] = h
            self._save_cache()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed to index tool '%s': %s", tool.name, exc)

    def remove_tool(self, name: str) -> None:
        """Remove *name* from the index and persist the change."""
        changed = any([
            self._embeddings.pop(name, None) is not None,
            bool(self._texts.pop(name, None)),
            bool(self._hashes.pop(name, None)),
        ])
        if changed:
            self._save_cache()

    def has_tool(self, name: str) -> bool:
        return name in self._embeddings

    def indexed_count(self) -> int:
        return len(self._embeddings)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        top_k: int | None = None,
        exclude: set[str] | None = None,
    ) -> list[dict[str, str]]:
        """Return tool dicts sorted by descending cosine similarity to *query*.

        Each entry has the shape ``{"name": tool_name, "description": "score tool_score"}``
        so the result is a plain ``list[dict]`` that serialises cleanly to JSON
        All indexed tools are returned (no minimum-score threshold) so the
        caller can inject even low-similarity tools into the system prompt
        with their scores — the list is simply ordered best-first so the
        most relevant tools appear at the top.

        Args:
            query: Natural-language description of the desired capability.
            top_k: Maximum results to return.  ``None`` returns all tools.
            exclude: Tool names to omit (e.g. ``{"tool_search"}`` to hide
                     the search tool itself from its own results).

        Returns:
            List of dicts in descending score order, or an empty list if the
            model is unavailable.
        """
        if not self._embeddings or not _NUMPY_AVAILABLE:
            return []
        model = _load_model()
        if model is None:
            return []

        try:
            q = model.encode(query, convert_to_numpy=True, normalize_embeddings=True)
            results: list[tuple[str, float]] = []
            for name, emb in self._embeddings.items():
                if exclude and name in exclude:
                    continue
                # Both vectors are unit-normalised → dot product == cosine similarity.
                score = float(np.dot(emb, q))
                results.append((name, score))

            results.sort(key=lambda x: x[1], reverse=True)
            if top_k is not None:
                results = results[:top_k]
            return [{"name": name, "description": f"score {score:.6f}"} for name, score in results]

        except Exception as exc:  # noqa: BLE001
            logger.debug("Embedding search failed: %s", exc)
            return []

    def all_with_scores(
        self,
        query: str,
        *,
        exclude: set[str] | None = None,
    ) -> list[dict[str, str]]:
        """Return every indexed tool with its similarity score, sorted descending."""
        return self.search(query, top_k=None, exclude=exclude)