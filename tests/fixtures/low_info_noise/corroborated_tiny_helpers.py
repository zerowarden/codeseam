from __future__ import annotations


def format_member(value: object) -> str:
    return escape(value)


def format_target(value: object) -> str:
    return escape(value)


def escape(value: object) -> str:
    return str(value).strip()
