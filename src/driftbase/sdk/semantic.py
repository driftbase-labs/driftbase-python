"""
Optional semantic clustering support via light_embed.

When the optional dependency is not installed, a clear warning is logged once
and embedding-based clustering is disabled. Install with:

    pip install driftbase[semantic]
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_EMBEDDING_MODEL_AVAILABLE = False
EmbeddingModel: type | None = (
    None  # Alias for TextEmbedding for backwards compatibility
)
TextEmbedding: type | None = None
_warned = False


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


# Run optional import at module load so warning is logged when semantic is first used
_optional_import()
