from __future__ import annotations

from collections.abc import Iterable


def dedupe(values: Iterable[str]) -> list[str]:
    return sorted({value for value in values if value})


def role_for(file_path: str, roles_by_path: dict[str, str]) -> str:
    return roles_by_path.get(file_path) or "unknown"


def roles_for(files: Iterable[str], roles_by_path: dict[str, str]) -> list[str]:
    return dedupe(role_for(file_path, roles_by_path) for file_path in files)
