from __future__ import annotations

from typing import cast

from codeseam.platform.json import Json


def merge_into(base: Json, incoming: Json) -> None:
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            merge_into(cast(Json, base[key]), cast(Json, value))
        else:
            base[key] = value


def set_nested(target: Json, path: tuple[str, ...], value: object) -> None:
    current = target
    for part in path[:-1]:
        current = cast(Json, current.setdefault(part, {}))
    current[path[-1]] = value
