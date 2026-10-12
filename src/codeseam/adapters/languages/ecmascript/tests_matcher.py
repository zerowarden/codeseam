from __future__ import annotations

from pathlib import Path

ECMASCRIPT_SUFFIXES = frozenset({".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts"})
TEST_STEM_SUFFIXES = (".test", ".spec", "-test", "-spec")
# Jasmine and Mocha keep specs in `spec/`; in Python that is usually an API schema.
SPEC_DIRS = frozenset({"spec", "specs"})


def matches_ecmascript_test_path(path: Path) -> bool:
    suffix = path.suffix.lower()
    if suffix not in ECMASCRIPT_SUFFIXES:
        return False
    stem = path.name.lower().removesuffix(suffix)
    return stem.endswith(TEST_STEM_SUFFIXES) or any(
        part.lower() in SPEC_DIRS for part in path.parts[:-1]
    )


__all__ = ["matches_ecmascript_test_path"]
