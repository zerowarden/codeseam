from __future__ import annotations

import fnmatch
import hashlib
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from codeseam.platform.errors import SourceChangedError
from codeseam.platform.paths import basename

GLOB_CHARS = frozenset("*?[")
BINARY_PROBE_BYTES = 8192
INCLUDE_ALL = ("**/*",)


@dataclass(frozen=True, slots=True)
class FileSelection:
    """User include and exclude globs; built-in excludes are added by the scan."""

    include: tuple[str, ...] = INCLUDE_ALL
    exclude: tuple[str, ...] = ()

    def payload(self) -> dict[str, list[str]]:
        return {"include": list(self.include), "exclude": list(self.exclude)}


def matches_any(path: str, patterns: list[str]) -> bool:
    return any(matches_glob(path, pattern) for pattern in patterns)


def matches_glob(path: str, pattern: str) -> bool:
    if pattern == "**/*":
        return True
    name = basename(path)
    if pattern.startswith("**/") and fnmatch.fnmatch(name, pattern[3:]):
        return True
    prefix = pattern.removesuffix("/**")
    if prefix != pattern and (path == prefix or path.startswith(prefix + "/")):
        return True
    return fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(name, pattern)


@dataclass(frozen=True)
class GlobMatcher:
    match_all: bool
    exact: frozenset[str]
    dir_prefixes: tuple[str, ...]
    basename_exact: frozenset[str]
    basename_patterns: tuple[str, ...]
    path_patterns: tuple[str, ...]

    @classmethod
    def from_patterns(cls, patterns: list[str]) -> GlobMatcher:
        exact: set[str] = set()
        dir_prefixes: list[str] = []
        basename_exact: set[str] = set()
        basename_patterns: list[str] = []
        path_patterns: list[str] = []
        match_all = False
        for pattern in patterns:
            if pattern == "**/*":
                match_all = True
                continue
            if pattern.startswith("**/"):
                suffix = pattern[3:]
                if "/" not in suffix and not _has_glob(suffix):
                    basename_exact.add(suffix)
                else:
                    basename_patterns.append(suffix)
                    path_patterns.append(pattern)
                continue
            prefix = pattern.removesuffix("/**")
            if prefix != pattern and not _has_glob(prefix):
                dir_prefixes.append(prefix.rstrip("/"))
                continue
            if not _has_glob(pattern):
                exact.add(pattern)
                if "/" not in pattern:
                    basename_exact.add(pattern)
                continue
            path_patterns.append(pattern)
            if "/" not in pattern:
                basename_patterns.append(pattern)
        return cls(
            match_all=match_all,
            exact=frozenset(exact),
            dir_prefixes=tuple(sorted(set(dir_prefixes))),
            basename_exact=frozenset(basename_exact),
            basename_patterns=tuple(dict.fromkeys(basename_patterns)),
            path_patterns=tuple(dict.fromkeys(path_patterns)),
        )

    def matches(self, path: str) -> bool:
        if self.match_all or path in self.exact:
            return True
        name = basename(path)
        if name in self.basename_exact:
            return True
        if any(path == prefix or path.startswith(prefix + "/") for prefix in self.dir_prefixes):
            return True
        if any(fnmatch.fnmatch(name, pattern) for pattern in self.basename_patterns):
            return True
        return any(fnmatch.fnmatch(path, pattern) for pattern in self.path_patterns)

    def matches_dir(self, path: str) -> bool:
        if self.matches(path):
            return True
        return self.matches(f"{path}/__dir__")


def _has_glob(pattern: str) -> bool:
    return bool(GLOB_CHARS & set(pattern))


def is_binary(path: Path) -> bool:
    try:
        return b"\0" in path.read_bytes()[:BINARY_PROBE_BYTES]
    except OSError:
        return True


def line_count(data: bytes) -> int:
    if not data:
        return 0
    return data.count(b"\n") + (0 if data.endswith(b"\n") else 1)


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def verified_bytes(path: Path, content_hash: str) -> bytes:
    """Read a file and check it still matches the hash the scan recorded.

    Without this, a file edited between the scan and the parse would be
    analysed as its new content but cached under its old hash, and reused if
    the old content ever came back.
    """

    data = path.read_bytes()
    if content_hash and sha256_bytes(data) != content_hash:
        raise SourceChangedError(f"{path} changed after the repository scan")
    return data


def sha256_text(text: str, *, errors: str = "strict") -> str:
    return sha256_bytes(text.encode("utf-8", errors=errors))


CONTENT_ID_HEX_LENGTH = 16


def content_ids(prefix: str, keys: Sequence[Sequence[str]]) -> list[str]:
    """Stable IDs from content keys, independent of what else is in the run.

    Pass keys in location order: a key that repeats (two identical same-name
    functions in one file) gets `-2`, `-3`, ... on its later occurrences.
    """

    seen: Counter[str] = Counter()
    ids: list[str] = []
    for key in keys:
        digest = hashlib.sha256("\x1f".join(key).encode("utf-8", errors="surrogatepass"))
        short = digest.hexdigest()[:CONTENT_ID_HEX_LENGTH]
        seen[short] += 1
        ids.append(f"{prefix}{short}" if seen[short] == 1 else f"{prefix}{short}-{seen[short]}")
    return ids


def qualified_symbol(symbol: str, container: str | None) -> str:
    return f"{container}.{symbol}" if container else symbol
