"""
Optional semantic clustering support via light_embed.

When the optional dependency is not installed, a clear warning is logged once
and embedding-based clustering is disabled. Install with:

    pip install driftbase[semantic]
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

logger = logging.getLogger(__name__)

_EMBEDDING_MODEL_AVAILABLE = False
EmbeddingModel: type | None = (
    None  # Alias for TextEmbedding for backwards compatibility
)
TextEmbedding: type | None = None
_warned = False
_cached_model: Any = None


def _optional_import() -> None:
    global EmbeddingModel, TextEmbedding, _EMBEDDING_MODEL_AVAILABLE, _warned
    if _warned or _EMBEDDING_MODEL_AVAILABLE:
        return
    try:
        from light_embed import (
            TextEmbedding as _TextEmbedding,  # type: ignore[import-not-found]
        )

        TextEmbedding = _TextEmbedding  # noqa: PLW0603
        EmbeddingModel = _TextEmbedding  # alias
        _EMBEDDING_MODEL_AVAILABLE = True
    except ImportError:
        _warned = True
        logger.warning(
            "light_embed is not installed. Semantic clustering is disabled. "
            "Install with: pip install driftbase[semantic]"
        )


def is_semantic_available() -> bool:
    """Return True if light_embed is installed and embedding model can be used."""
    _optional_import()
    return _EMBEDDING_MODEL_AVAILABLE


def get_embedding_model(**kwargs: Any) -> Any:
    """
    Return a TextEmbedding (light_embed) instance if light_embed is installed, else None.
    Logs a clear warning once when not installed.
    """
    _optional_import()
    if TextEmbedding is None:
        return None
    return TextEmbedding(**kwargs)


def compute_semantic_cluster_id(text: str) -> str | None:
    """
    Compute an embedding-based cluster id for a run summary (e.g. final AI content).
    Used to group runs by semantic similarity in drift reports.
    Returns None if semantic is unavailable or text is empty; otherwise a string like "cluster_a1b2c3d4".
    """
    if not text or not text.strip():
        return None
    _optional_import()
    if not _EMBEDDING_MODEL_AVAILABLE or TextEmbedding is None:
        return None
    global _cached_model
    try:
        if _cached_model is None:
            _cached_model = TextEmbedding(
                model_name_or_path="sentence-transformers/all-MiniLM-L6-v2"
            )
        emb = _cached_model.encode([text.strip()])
        if emb is None or (hasattr(emb, "__len__") and len(emb) == 0):
            return None
        vec = emb[0] if hasattr(emb, "__len__") and len(emb) else emb
        raw = vec.tobytes() if hasattr(vec, "tobytes") else str(vec).encode()
        h = hashlib.sha256(raw).hexdigest()[:8]
        return f"cluster_{h}"
    except Exception as e:
        logger.debug("Semantic cluster id failed: %s", e)
        return None


# Run optional import at module load so warning is logged when semantic is first used
_optional_import()
