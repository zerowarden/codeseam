from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence

MAX_UINT64 = (1 << 64) - 1
DEFAULT_MINHASH_SIZE = 64
DEFAULT_LSH_BANDS = 16

type MinHashSignature = tuple[int, ...]
type LshBandKey = tuple[int, tuple[int, ...]]


def minhash_signature(
    values: Iterable[str],
    *,
    size: int = DEFAULT_MINHASH_SIZE,
) -> MinHashSignature:
    """Build a deterministic MinHash signature from unordered string values."""

    items = tuple(sorted(set(values)))
    if size <= 0:
        return ()
    if not items:
        return tuple(MAX_UINT64 for _ in range(size))
    return tuple(min(_hash64(index, item) for item in items) for index in range(size))


def lsh_band_keys(
    signature: Sequence[int],
    *,
    bands: int = DEFAULT_LSH_BANDS,
) -> tuple[LshBandKey, ...]:
    """Split a MinHash signature into stable LSH band keys."""

    if bands <= 0 or not signature:
        return ()
    band_size = len(signature) // bands
    if band_size <= 0 or len(signature) % bands:
        raise ValueError("MinHash signature length must be divisible by band count.")
    return tuple(
        (band, tuple(signature[start : start + band_size]))
        for band in range(bands)
        for start in (band * band_size,)
    )


def hash64_band(band: Sequence[int]) -> int:
    """Return a stable compact hash for an LSH band."""

    payload = "|".join(str(value) for value in band).encode("ascii")
    return int.from_bytes(hashlib.blake2b(payload, digest_size=8).digest(), "big")


def _hash64(seed: int, value: str) -> int:
    payload = f"{seed}:{value}".encode("utf-8", errors="surrogatepass")
    return int.from_bytes(hashlib.blake2b(payload, digest_size=8).digest(), "big")


__all__ = [
    "DEFAULT_LSH_BANDS",
    "DEFAULT_MINHASH_SIZE",
    "LshBandKey",
    "MinHashSignature",
    "hash64_band",
    "lsh_band_keys",
    "minhash_signature",
]
