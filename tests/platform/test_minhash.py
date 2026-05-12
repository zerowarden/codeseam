from __future__ import annotations

import pytest

from codeseam.platform import MAX_UINT64, hash64_band, lsh_band_keys, minhash_signature

SIGNATURE_SIZE = 16
BAND_COUNT = 4


def test_minhash_signature_is_deterministic_order_independent_and_duplicate_insensitive() -> None:
    items = ("STMT:RETURN:ARG", "CALL:json.dumps", "FLOW:ARG->RETURN")

    first = minhash_signature(items, size=SIGNATURE_SIZE)
    second = minhash_signature(tuple(reversed(items)), size=SIGNATURE_SIZE)
    with_duplicate = minhash_signature((*items, "CALL:json.dumps"), size=SIGNATURE_SIZE)

    assert first == second
    assert first == with_duplicate
    assert len(first) == SIGNATURE_SIZE
    assert all(0 <= value <= MAX_UINT64 for value in first)


def test_minhash_signature_changes_when_structural_material_changes() -> None:
    base = minhash_signature(("STMT:RETURN:ARG", "FLOW:ARG->RETURN"), size=SIGNATURE_SIZE)
    changed = minhash_signature(("STMT:RETURN:ARG", "FLOW:ARG->CALL"), size=SIGNATURE_SIZE)

    assert base != changed


def test_lsh_band_keys_are_deterministic_and_partition_the_signature() -> None:
    signature = minhash_signature(("STMT:RETURN:ARG", "CALL:json.dumps"), size=SIGNATURE_SIZE)
    bands = lsh_band_keys(signature, bands=BAND_COUNT)

    assert bands == lsh_band_keys(signature, bands=BAND_COUNT)
    assert len(bands) == BAND_COUNT
    assert tuple(value for _, band in bands for value in band) == signature
    assert tuple(index for index, _ in bands) == (0, 1, 2, 3)


def test_lsh_band_hash_is_deterministic_and_order_sensitive() -> None:
    band = minhash_signature(("STMT:RETURN:ARG", "CALL:json.dumps"), size=SIGNATURE_SIZE)[
        :BAND_COUNT
    ]

    assert hash64_band(band) == hash64_band(tuple(band))
    assert hash64_band(tuple(reversed(band))) != hash64_band(band)


def test_empty_minhash_signature_uses_max_hash_sentinel() -> None:
    assert minhash_signature((), size=4) == (MAX_UINT64, MAX_UINT64, MAX_UINT64, MAX_UINT64)


def test_lsh_band_keys_require_even_band_partition() -> None:
    with pytest.raises(ValueError, match="divisible"):
        lsh_band_keys((1, 2, 3), bands=2)
