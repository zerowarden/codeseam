from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields, is_dataclass, replace
from typing import Any, cast

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


def with_overrides[T](instance: T, overrides: Mapping[str, object], *, path: str = "") -> T:
    """Copy a frozen dataclass tree with validated overrides.

    Nested dataclasses take nested mappings. Each value must match the type of
    the default it replaces (ints are accepted for floats); unknown keys and
    other field types are rejected with a ValueError naming the dotted path.
    """

    if not is_dataclass(instance) or isinstance(instance, type):
        raise TypeError("with_overrides expects a dataclass instance")
    known = {item.name for item in fields(instance)}
    changes: dict[str, Any] = {}
    for key, value in overrides.items():
        name = f"{path}{key}"
        if key not in known:
            raise ValueError(f"unknown setting {name!r}")
        changes[key] = _override_value(getattr(instance, key), value, name)
    return replace(instance, **changes)


def _override_value(current: object, value: object, name: str) -> object:
    if is_dataclass(current) and not isinstance(current, type):
        if not isinstance(value, Mapping):
            raise ValueError(f"{name!r} is a table of settings")
        return with_overrides(current, cast(Mapping[str, object], value), path=f"{name}.")
    if isinstance(current, bool) or isinstance(value, bool):
        if type(current) is bool and type(value) is bool:
            return value
    elif isinstance(current, int) and isinstance(value, int):
        return value
    elif isinstance(current, float) and isinstance(value, int | float):
        return float(value)
    elif isinstance(current, str) and isinstance(value, str):
        return value
    raise ValueError(f"{name!r} must be {type(current).__name__}, not {value!r}")
