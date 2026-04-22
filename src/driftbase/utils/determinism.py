"""
Deterministic randomness utilities for reproducible drift detection.

All random operations (bootstrap sampling, anomaly detection, etc.) should use
get_rng() to ensure reproducible results across runs.
"""

from __future__ import annotations

import hashlib

import numpy as np

from driftbase.config import get_settings


def _stable_hash(s: str) -> int:
    """
    Compute a stable hash of a string that is consistent across Python processes.

    Python's built-in hash() is randomized per-process for security, making it
    unsuitable for reproducible seeding. This function uses SHA-256 which is
    deterministic across all invocations.

    Args:
        s: String to hash

    Returns:
        Integer hash value (first 8 bytes of SHA-256 digest as big-endian int)
    """
    return int.from_bytes(
        hashlib.sha256(s.encode("utf-8")).digest()[:8],
        "big",
    )


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

    # Combine base_seed with stable hash of salt for cross-process determinism
    # Use Knuth's hash-combining constant to ensure base_seed changes aren't
    # trivially overridden by salt values
    salt_hash = _stable_hash(salt)
    combined_seed = (base_seed * 2654435761 + salt_hash) & 0xFFFFFFFF
    return np.random.default_rng(combined_seed)
