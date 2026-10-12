"""Data-only codec for persistent cache blobs.

Cache databases live inside the analysed repository by default, so their
contents are untrusted input. Blobs are tagged JSON: decoding rebuilds plain
containers, enums, and dataclasses defined in already-loaded ``codeseam``
modules by assigning their fields directly. No constructor, ``__setstate__``,
import, or other code path is reachable from blob contents.
"""

from __future__ import annotations

import dataclasses
import enum
import json
import sys
from collections import Counter

BLOB_MAGIC = b"codeseam-blob:json.v1\n"
TRUSTED_MODULE_PREFIX = "codeseam."


class CacheBlobError(ValueError):
    """Raised when a payload is not a valid data-only cache blob."""


def cache_blob(payload: object) -> bytes:
    encoded = json.dumps(_encode(payload), separators=(",", ":"), ensure_ascii=False)
    return BLOB_MAGIC + encoded.encode("utf-8")


def load_cache_blob(payload: bytes) -> object:
    if not payload.startswith(BLOB_MAGIC):
        raise CacheBlobError("Unsupported cache blob format.")
    try:
        raw = json.loads(payload[len(BLOB_MAGIC) :])
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CacheBlobError("Malformed cache blob.") from exc
    return _decode(raw)


_SEQUENCE_TAGS: dict[type, str] = {tuple: "t", frozenset: "z", set: "s"}
_MAPPING_TAGS: dict[type, str] = {dict: "d", Counter: "n"}


def _encode(value: object) -> object:
    if value is None or type(value) in (bool, int, float, str):
        return value
    if isinstance(value, enum.Enum):
        return {"e": _type_name(type(value)), "v": _encode(value.value)}
    if type(value) is list:
        return [_encode(item) for item in value]
    if isinstance(value, tuple | frozenset | set) and type(value) in _SEQUENCE_TAGS:
        return {_SEQUENCE_TAGS[type(value)]: [_encode(item) for item in value]}
    if isinstance(value, dict) and type(value) in _MAPPING_TAGS:
        pairs = [[_encode(key), _encode(item)] for key, item in value.items()]
        return {_MAPPING_TAGS[type(value)]: pairs}
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            "c": _type_name(type(value)),
            "f": {field.name: _encode(getattr(value, field.name)) for field in _fields(value)},
        }
    raise TypeError(f"Unsupported cache value type: {type(value).__qualname__}")


def _decode(value: object) -> object:  # noqa: PLR0911
    if isinstance(value, list):
        return [_decode(item) for item in value]
    if not isinstance(value, dict):
        return value
    if len(value) == 1:
        ((tag, body),) = value.items()
        items = _list(body)
        if tag == "t":
            return tuple(_decode(item) for item in items)
        if tag == "z":
            return frozenset(_decode(item) for item in items)
        if tag == "s":
            return {_decode(item) for item in items}
        if tag in ("d", "n"):
            pairs = ((_decode(key), _decode(item)) for key, item in map(_pair, items))
            return dict(pairs) if tag == "d" else Counter(dict(pairs))
    if value.keys() == {"e", "v"}:
        enum_type = _trusted_type(value["e"])
        if not issubclass(enum_type, enum.Enum):
            raise CacheBlobError(f"Not an enum: {value['e']!r}.")
        return enum_type(_decode(value["v"]))
    if value.keys() == {"c", "f"}:
        return _decode_dataclass(value["c"], value["f"])
    raise CacheBlobError("Unknown cache blob node.")


def _decode_dataclass(name: object, raw_fields: object) -> object:
    cls = _trusted_type(name)
    if not dataclasses.is_dataclass(cls) or not isinstance(raw_fields, dict):
        raise CacheBlobError(f"Not a dataclass record: {name!r}.")
    if raw_fields.keys() != {field.name for field in _fields(cls)}:
        raise CacheBlobError(f"Cached fields do not match {name!r}.")
    instance = object.__new__(cls)
    for field_name, raw in raw_fields.items():
        object.__setattr__(instance, field_name, _decode(raw))
    return instance


def _trusted_type(name: object) -> type:
    if not isinstance(name, str):
        raise CacheBlobError("Type name must be a string.")
    module_name, _, qualname = name.partition(":")
    module = sys.modules.get(module_name) if module_name.startswith(TRUSTED_MODULE_PREFIX) else None
    resolved: object = module
    for part in qualname.split(".") if module is not None and qualname else ():
        resolved = getattr(resolved, part, None)
    if not isinstance(resolved, type) or resolved.__module__ != module_name:
        raise CacheBlobError(f"Untrusted cache type: {name!r}.")
    return resolved


def _type_name(cls: type) -> str:
    return f"{cls.__module__}:{cls.__qualname__}"


def _fields(value: object) -> tuple[dataclasses.Field[object], ...]:
    return dataclasses.fields(value)  # type: ignore[arg-type]


def _list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise CacheBlobError("Expected a list body.")
    return value


def _pair(value: object) -> tuple[object, object]:
    if not isinstance(value, list) or len(value) != 2:  # noqa: PLR2004
        raise CacheBlobError("Expected a key/value pair.")
    return value[0], value[1]
