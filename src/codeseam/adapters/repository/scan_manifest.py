from __future__ import annotations

from dataclasses import dataclass, field
from os import stat_result
from pathlib import Path

from codeseam.platform import Json, JsonValue, as_json_object, loads_json, write_jsonable_atomic
from codeseam.version import SCAN_MANIFEST_SCHEMA_VERSION

SCAN_MANIFEST_FILENAME = "scan_manifest.json"
ENTRY_FIELD_COUNT = 5


@dataclass(frozen=True, slots=True)
class FileContentSummary:
    size_bytes: int
    line_count: int
    content_hash: str


@dataclass(frozen=True, slots=True)
class ScanManifestEntry:
    size_bytes: int
    mtime_ns: int
    ctime_ns: int
    line_count: int
    content_hash: str

    def matches(self, stat: stat_result) -> bool:
        return (
            self.size_bytes == stat.st_size
            and self.mtime_ns == stat.st_mtime_ns
            and self.ctime_ns == stat.st_ctime_ns
        )

    def summary(self) -> FileContentSummary:
        return FileContentSummary(
            size_bytes=self.size_bytes,
            line_count=self.line_count,
            content_hash=self.content_hash,
        )

    def payload(self) -> list[JsonValue]:
        return [
            self.size_bytes,
            self.mtime_ns,
            self.ctime_ns,
            self.line_count,
            self.content_hash,
        ]


@dataclass(slots=True)
class ScanManifest:
    entries: dict[str, ScanManifestEntry] = field(default_factory=dict)
    _current: dict[str, ScanManifestEntry] = field(default_factory=dict)

    def content_summary(self, path: str, stat: stat_result) -> FileContentSummary | None:
        entry = self.entries.get(path)
        if entry is None or not entry.matches(stat):
            return None
        self._current[path] = entry
        return entry.summary()

    def remember(self, path: str, stat: stat_result, summary: FileContentSummary) -> None:
        self._current[path] = ScanManifestEntry(
            size_bytes=summary.size_bytes,
            mtime_ns=stat.st_mtime_ns,
            ctime_ns=stat.st_ctime_ns,
            line_count=summary.line_count,
            content_hash=summary.content_hash,
        )

    def payload(self) -> Json:
        return {
            "schema_version": SCAN_MANIFEST_SCHEMA_VERSION,
            "entries": {path: entry.payload() for path, entry in sorted(self._current.items())},
        }


def scan_manifest_path(cache_root: Path) -> Path:
    return cache_root / SCAN_MANIFEST_FILENAME


def load_scan_manifest(path: Path) -> ScanManifest:
    try:
        payload = loads_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ScanManifest()
    root = as_json_object(payload)
    if root.get("schema_version") != SCAN_MANIFEST_SCHEMA_VERSION:
        return ScanManifest()
    entries = {
        path: entry
        for path, raw_entry in as_json_object(root.get("entries")).items()
        if isinstance(path, str) and (entry := _entry_from_payload(raw_entry)) is not None
    }
    return ScanManifest(entries)


def store_scan_manifest(path: Path, manifest: ScanManifest) -> None:
    try:
        write_jsonable_atomic(path, manifest.payload())
    except OSError:
        return


def _entry_from_payload(value: object) -> ScanManifestEntry | None:
    if not isinstance(value, list | tuple) or len(value) != ENTRY_FIELD_COUNT:
        return None
    size_bytes, mtime_ns, ctime_ns, line_count, content_hash = value
    if not all(_valid_int(item) for item in (size_bytes, mtime_ns, ctime_ns, line_count)):
        return None
    if not isinstance(content_hash, str) or not content_hash.startswith("sha256:"):
        return None
    return ScanManifestEntry(
        size_bytes=size_bytes,
        mtime_ns=mtime_ns,
        ctime_ns=ctime_ns,
        line_count=line_count,
        content_hash=content_hash,
    )


def _valid_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


__all__ = [
    "FileContentSummary",
    "SCAN_MANIFEST_FILENAME",
    "ScanManifest",
    "ScanManifestEntry",
    "load_scan_manifest",
    "scan_manifest_path",
    "store_scan_manifest",
]
