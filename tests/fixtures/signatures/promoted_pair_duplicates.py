from __future__ import annotations


def ci_single_line(value: object) -> str:
    return " ".join(str(value or "").split())


def output_single_line(value: object) -> str:
    return " ".join(str(value or "").split())


def fallback_label(value: object) -> str:
    return str(value) if value else "none"
