from __future__ import annotations

from enum import StrEnum


class LanguageFamily(StrEnum):
    UNKNOWN = "unknown"
    PYTHON = "python"
    ECMASCRIPT_TYPESCRIPT = "ecmascript_typescript"


class ExtractionConfidence(StrEnum):
    UNKNOWN = "unknown"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @property
    def rank(self) -> int:
        return {
            ExtractionConfidence.UNKNOWN: 0,
            ExtractionConfidence.LOW: 1,
            ExtractionConfidence.MEDIUM: 2,
            ExtractionConfidence.HIGH: 3,
        }[self]


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


__all__ = ["AdapterId", "ExtractionConfidence", "LanguageFamily", "adapter_id", "language_family"]
