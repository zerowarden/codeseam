from __future__ import annotations


def _member_label(value: object) -> str:
    if not isinstance(value, dict):
        return "unknown"
    path = text(value.get("file"))
    line = text(value.get("start_line"))
    symbol = text(value.get("symbol"))
    return f"{path}:{line} {symbol}".strip()
