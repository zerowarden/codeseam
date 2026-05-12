from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, TypeVar

from codeseam.adapters.languages.capabilities import AdapterCapabilities
from codeseam.adapters.languages.manifests import ManifestMatcher
from codeseam.analysis import AdapterId, FunctionIR, FunctionRecord, PolicyConstant, SignatureRecord

T = TypeVar("T")


class LanguageRunCacheProtocol(Protocol):
    """Per-run language extraction cache boundary."""

    def source_bytes(self, context: Any) -> bytes: ...

    def analysis(
        self,
        context: Any,
        namespace: str,
        build: Callable[[], T],
    ) -> T: ...

    def cached_analysis(
        self,
        context: Any,
        namespace: str,
    ) -> object | None: ...

    def functions(
        self,
        context: Any,
        build: Callable[[], list[FunctionIR]],
    ) -> list[FunctionIR]: ...


@dataclass(frozen=True)
class LanguageAnalysisContext:
    path: Path
    relative_path: str
    role: str
    language: str
    content_hash: str = ""
    run_cache: LanguageRunCacheProtocol | None = None


class LanguageAdapter(Protocol):
    adapter_id: AdapterId
    languages: frozenset[str]
    manifest_matchers: tuple[ManifestMatcher, ...]
    capabilities: AdapterCapabilities

    def extract_analysis(self, context: LanguageAnalysisContext) -> LanguageAdapterAnalysis: ...


class StaticLanguageSupport:
    languages: frozenset[str]
    manifest_matchers: tuple[ManifestMatcher, ...] = ()
    capabilities = AdapterCapabilities()


@dataclass(frozen=True)
class LanguageAdapterAnalysis:
    functions: tuple[FunctionRecord, ...]
    signatures: tuple[SignatureRecord, ...]
    policy_constants: tuple[PolicyConstant, ...] = ()


__all__ = [
    "LanguageAdapter",
    "LanguageAdapterAnalysis",
    "LanguageAnalysisContext",
    "LanguageRunCacheProtocol",
    "StaticLanguageSupport",
]
