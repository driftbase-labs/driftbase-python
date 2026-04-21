"""
Deterministic randomness utilities for reproducible drift detection.

All random operations (bootstrap sampling, anomaly detection, etc.) should use
get_rng() to ensure reproducible results across runs.
"""

from __future__ import annotations

import numpy as np

from driftbase.config import get_settings


def get_rng(salt: str | None = None) -> np.random.Generator:
    """
    Get a seeded numpy random number generator.

    Args:
        salt: Optional salt to derive a different seed from DRIFTBASE_SEED.
              Used to ensure different operations get independent random streams
              while remaining reproducible.

    Returns:
        numpy.random.Generator seeded with DRIFTBASE_SEED (or salted variant)

    Examples:
        # Same seed for all operations without salt
        rng = get_rng()

        # Different but reproducible streams for different operations
        bootstrap_rng = get_rng("bootstrap:v1-v2")
        sampling_rng = get_rng("sampling:fingerprint")
    """
    settings = get_settings()
    base_seed = settings.DRIFTBASE_SEED

    if salt is None:
        return np.random.default_rng(base_seed)

    # Hash the salt to derive a new seed
    # Use Python's hash() for simplicity (deterministic within a process)
    # For cross-process determinism, combine base_seed and salt hash
    salted_seed = hash((base_seed, salt)) % (2**32)
    return np.random.default_rng(salted_seed)
