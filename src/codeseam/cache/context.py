from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, TypeVar, cast

from codeseam.analysis import FunctionIR
from codeseam.cache.main import Cache, CacheCodec, CacheWriteBuffer
from codeseam.cache.store import PersistentCache

T = TypeVar("T")


class _LanguageAnalysisContext(Protocol):
    @property
    def path(self) -> Path: ...

    @property
    def content_hash(self) -> str: ...

    @property
    def language(self) -> str: ...

    @property
    def role(self) -> str: ...


@dataclass(frozen=True)
class AnalysisCacheContext:
    persistent: PersistentCache
    file_analysis_enabled: bool
    relation_pair_enabled: bool
    language: LanguageRunCache | None = None
    write_buffer: CacheWriteBuffer | None = None

    def cache[T](self, codec: CacheCodec[T]) -> Cache[T]:
        return Cache(self.persistent, codec, self.write_buffer)

    def flush(self) -> None:
        if self.write_buffer is not None:
            self.write_buffer.flush(self.persistent)


@dataclass
class LanguageRunCache:
    _sources: dict[tuple[str, str], bytes] = field(default_factory=dict)
    _analysis: dict[tuple[str, str, str], object] = field(default_factory=dict)
    _functions: dict[tuple[str, str, str, str], tuple[FunctionIR, ...]] = field(
        default_factory=dict,
    )

    def source_bytes(self, context: _LanguageAnalysisContext) -> bytes:
        key = _source_key(context)
        if key not in self._sources:
            self._sources[key] = context.path.read_bytes()
        return self._sources[key]

    def analysis(
        self,
        context: _LanguageAnalysisContext,
        namespace: str,
        build: Callable[[], T],
    ) -> T:
        key = (*_source_key(context), namespace)
        if key not in self._analysis:
            self._analysis[key] = build()
        return cast(T, self._analysis[key])

    def cached_analysis(
        self,
        context: _LanguageAnalysisContext,
        namespace: str,
    ) -> object | None:
        return self._analysis.get((*_source_key(context), namespace))

    def functions(
        self,
        context: _LanguageAnalysisContext,
        build: Callable[[], list[FunctionIR]],
    ) -> list[FunctionIR]:
        key = _functions_key(context)
        if key not in self._functions:
            self._functions[key] = tuple(build())
        return list(self._functions[key])


def _source_key(context: _LanguageAnalysisContext) -> tuple[str, str]:
    return (str(context.path), context.content_hash)


def _functions_key(context: _LanguageAnalysisContext) -> tuple[str, str, str, str]:
    return (
        str(context.path),
        context.language,
        context.content_hash,
        context.role,
    )
