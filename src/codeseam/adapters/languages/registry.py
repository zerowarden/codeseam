from __future__ import annotations

from collections.abc import Callable, Iterable

from codeseam.adapters.languages.base import LanguageAdapter
from codeseam.adapters.languages.capabilities import AdapterCapabilitySummary
from codeseam.adapters.languages.manifests import ManifestMatcher


class LanguageRegistry:
    def __init__(self, adapters: list[LanguageAdapter]) -> None:
        self._by_language = _index_adapters(adapters, lambda adapter: adapter.languages)

    def adapter_for_language(self, language: str) -> LanguageAdapter | None:
        """Case-insensitive: records store `typescript`, adapters declare `TypeScript`."""

        return self._by_language.get(language.casefold())

    def capability_summaries(
        self,
        languages: Iterable[str],
    ) -> tuple[AdapterCapabilitySummary, ...]:
        summaries: list[AdapterCapabilitySummary] = []
        seen: set[str] = set()
        for language in sorted(set(languages)):
            adapter = self.adapter_for_language(language)
            if adapter is None:
                continue
            key = f"{language}\0{adapter.adapter_id.value}"
            if key in seen:
                continue
            seen.add(key)
            summaries.append(
                AdapterCapabilitySummary(
                    language=language,
                    adapter_id=adapter.adapter_id,
                    capabilities=adapter.capabilities,
                )
            )
        return tuple(summaries)

    def manifest_matchers(self) -> tuple[ManifestMatcher, ...]:
        return tuple(
            matcher for adapter in self._adapters() for matcher in adapter.manifest_matchers
        )

    def _adapters(self) -> tuple[LanguageAdapter, ...]:
        return tuple(dict.fromkeys(self._by_language.values()))

    def adapters(self) -> tuple[LanguageAdapter, ...]:
        return self._adapters()


__all__ = ["LanguageRegistry"]


def _index_adapters(
    adapters: list[LanguageAdapter],
    keys_for: Callable[[LanguageAdapter], Iterable[str]],
) -> dict[str, LanguageAdapter]:
    return {key.casefold(): adapter for adapter in adapters for key in keys_for(adapter)}
