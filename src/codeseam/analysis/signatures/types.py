from __future__ import annotations

from enum import StrEnum


class SignatureTypeClass(StrEnum):
    UNKNOWN = "unknown"
    TEXT = "text"
    NUMBER = "number"
    BOOLEAN = "boolean"
    COLLECTION = "collection"
    MAPPING = "mapping"
    OPAQUE = "opaque"
    DOMAIN = "domain"


class BoundarySpecificity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SignatureTypeSource(StrEnum):
    DECLARED_SYNTAX = "declared_syntax"
    FALLBACK = "fallback"
    INFERRED = "inferred"
    UNKNOWN = "unknown"


UNKNOWN_TYPES = frozenset({"", "unknown", "any", "auto", "dyn", "never", "none", "void"})
TEXT_TYPES = frozenset({"str", "string", "charsequence", "text"})
NUMBER_TYPES = frozenset(
    {
        "int",
        "integer",
        "float",
        "double",
        "number",
        "usize",
        "isize",
        "u8",
        "u16",
        "u32",
        "u64",
        "i8",
        "i16",
        "i32",
        "i64",
        "f32",
        "f64",
    }
)
BOOLEAN_TYPES = frozenset({"bool", "boolean"})
OPAQUE_TYPES = frozenset({"object", "jsonobject", "json", "serdejson::value"})
COLLECTION_PREFIXES = ("list", "array", "seq", "sequence", "tuple", "set", "vec", "vector")
MAPPING_PREFIXES = ("dict", "dictionary", "map", "hashmap", "record")


def classify_signature_type(value: str) -> SignatureTypeClass:
    normalized = _type_key(value)
    stripped = value.strip()
    bracket_inner = _bracket_inner_type(stripped)
    if (bracket_inner and ":" in bracket_inner) or _has_prefix(normalized, MAPPING_PREFIXES):
        return SignatureTypeClass.MAPPING
    if stripped.endswith("[]") or bracket_inner or _has_prefix(normalized, COLLECTION_PREFIXES):
        return SignatureTypeClass.COLLECTION
    exact_classes = (
        (UNKNOWN_TYPES, SignatureTypeClass.UNKNOWN),
        (TEXT_TYPES, SignatureTypeClass.TEXT),
        (NUMBER_TYPES, SignatureTypeClass.NUMBER),
        (BOOLEAN_TYPES, SignatureTypeClass.BOOLEAN),
        (OPAQUE_TYPES, SignatureTypeClass.OPAQUE),
    )
    for aliases, type_class in exact_classes:
        if normalized in aliases:
            return type_class
    return SignatureTypeClass.DOMAIN


def collection_element_type_class(value: str) -> SignatureTypeClass | None:
    inner = _collection_inner_type(value)
    return classify_signature_type(inner) if inner else None


def _type_key(value: str) -> str:
    return value.replace(" ", "").replace("_", "").replace(".", "").replace("[]", "").lower()


def _has_prefix(value: str, prefixes: tuple[str, ...]) -> bool:
    return any(
        value == prefix or value.startswith(f"{prefix}[") or value.startswith(f"{prefix}<")
        for prefix in prefixes
    )


def _collection_inner_type(value: str) -> str:
    stripped = value.strip()
    if stripped.endswith("[]"):
        return stripped.removesuffix("[]")
    if inner := _bracket_inner_type(stripped):
        return inner
    if "[" in stripped and stripped.endswith("]"):
        return stripped.split("[", 1)[1][:-1]
    if "<" in stripped and stripped.endswith(">"):
        return stripped.split("<", 1)[1][:-1]
    return ""


def _bracket_inner_type(stripped: str) -> str:
    return stripped[1:-1] if stripped.startswith("[") and stripped.endswith("]") else ""


__all__ = [
    "BoundarySpecificity",
    "SignatureTypeClass",
    "SignatureTypeSource",
    "classify_signature_type",
    "collection_element_type_class",
]
