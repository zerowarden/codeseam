from __future__ import annotations

from enum import StrEnum


class LanguageFamily(StrEnum):
    UNKNOWN = "unknown"
    PYTHON = "python"
    ECMASCRIPT_TYPESCRIPT = "ecmascript_typescript"


class AdapterId(StrEnum):
    UNKNOWN = "unknown"
    PYTHON_AST = "python_ast"
    TREESITTER_ECMASCRIPT_TYPESCRIPT = "treesitter_ecmascript_typescript"


def language_family(value: object) -> LanguageFamily:
    if isinstance(value, LanguageFamily):
        return value
    try:
        return LanguageFamily(str(value).casefold())
    except (TypeError, ValueError):
        return LanguageFamily.UNKNOWN


def adapter_id(value: object) -> AdapterId:
    if isinstance(value, AdapterId):
        return value
    try:
        return AdapterId(str(value).casefold())
    except (TypeError, ValueError):
        return AdapterId.UNKNOWN


__all__ = ["AdapterId", "LanguageFamily", "adapter_id", "language_family"]
