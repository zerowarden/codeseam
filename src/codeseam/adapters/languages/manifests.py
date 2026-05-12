from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ManifestMatcher:
    kind: str
    patterns: tuple[str, ...]

    def matches(self, path: str) -> bool:
        name = Path(path).name
        return any(fnmatch.fnmatch(name, pattern) for pattern in self.patterns)


def matching_manifest_kind(path: str, matchers: tuple[ManifestMatcher, ...]) -> str | None:
    for matcher in matchers:
        if matcher.matches(path):
            return matcher.kind
    return None
