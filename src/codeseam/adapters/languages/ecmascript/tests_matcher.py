from __future__ import annotations


def matches_ecmascript_test_name(stem: str, suffix: str) -> bool:
    if suffix not in {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts"}:
        return False
    return stem.endswith((".test", ".spec", "-test", "-spec"))


__all__ = ["matches_ecmascript_test_name"]
