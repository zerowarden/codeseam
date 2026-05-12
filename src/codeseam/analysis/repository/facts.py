from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from codeseam.analysis.repository.models import FileRecord, RepositoryManifest, RepositoryScan
from codeseam.version import REPOSITORY_FACTS_CACHE_VALUE_VERSION

type FileRecordCacheValue = tuple[str, str, int, int, str, str, bool, bool, bool, bool]
type ManifestCacheValue = tuple[str, str]
type RepositoryFactsCacheValue = tuple[
    str,
    tuple[FileRecordCacheValue, ...],
    tuple[str, ...],
    tuple[ManifestCacheValue, ...],
]

REPOSITORY_FACTS_CACHE_FIELD_COUNT = 4
FILE_RECORD_CACHE_FIELD_COUNT = 10
MANIFEST_CACHE_FIELD_COUNT = 2


@dataclass(frozen=True, slots=True)
class RepositoryFacts:
    """Normalized repository facts

    `RepositoryScan` is the raw scanner output. `RepositoryFacts` is the compact,
    deterministic view the pipeline consumes after scanning. It keeps common
    lookups precomputed so downstream stages do not rebuild path, role, language,
    and manifest summaries independently.
    """

    records: tuple[FileRecord, ...]
    selected_paths: tuple[str, ...]
    manifests: tuple[RepositoryManifest, ...]
    records_by_path: dict[str, FileRecord]
    roles_by_path: dict[str, str]
    languages_by_path: dict[str, str]
    language_counts: dict[str, int]
    role_counts: dict[str, int]

    @property
    def selected_file_count(self) -> int:
        return len(self.selected_paths)

    @property
    def skipped_file_count(self) -> int:
        return max(0, len(self.records) - len(self.selected_paths))


def build_repository_facts(scan: RepositoryScan) -> RepositoryFacts:
    records = tuple(scan.records)
    selected_paths = tuple(scan.selected_paths)
    manifests = tuple(scan.manifests)
    records_by_path = {record.path: record for record in records}
    roles_by_path = {record.path: record.role for record in records}
    languages_by_path = {record.path: record.language for record in records}
    return RepositoryFacts(
        records=records,
        selected_paths=selected_paths,
        manifests=manifests,
        records_by_path=records_by_path,
        roles_by_path=roles_by_path,
        languages_by_path=languages_by_path,
        language_counts=dict(Counter(record.language for record in records)),
        role_counts=dict(Counter(record.role for record in records)),
    )


def repository_facts_cache_value(facts: RepositoryFacts) -> RepositoryFactsCacheValue:
    """Return the compact pickle-blob value for repository facts."""

    return (
        REPOSITORY_FACTS_CACHE_VALUE_VERSION,
        tuple(_file_record_cache_value(record) for record in facts.records),
        tuple(facts.selected_paths),
        tuple(_manifest_cache_value(manifest) for manifest in facts.manifests),
    )


def repository_facts_from_cache_value(value: object) -> RepositoryFacts | None:
    if not isinstance(value, tuple) or len(value) != REPOSITORY_FACTS_CACHE_FIELD_COUNT:
        return None
    schema_version, raw_records, raw_selected_paths, raw_manifests = value
    if schema_version != REPOSITORY_FACTS_CACHE_VALUE_VERSION:
        return None
    records = _file_records_from_cache_value(raw_records)
    selected_paths = _strings_from_cache_value(raw_selected_paths)
    manifests = _manifests_from_cache_value(raw_manifests)
    if records is None or selected_paths is None or manifests is None:
        return None
    return build_repository_facts(
        RepositoryScan(
            records=records,
            selected_paths=selected_paths,
            manifests=manifests,
        )
    )


def _file_record_cache_value(
    record: FileRecord,
) -> FileRecordCacheValue:
    return (
        record.path,
        record.language,
        record.size_bytes,
        record.line_count,
        record.content_hash,
        record.role,
        record.is_generated,
        record.is_vendor,
        record.is_test,
        record.is_build_output,
    )


def _file_records_from_cache_value(value: object) -> list[FileRecord] | None:
    if not isinstance(value, tuple):
        return None
    records: list[FileRecord] = []
    for item in value:
        record = _file_record_from_cache_value(item)
        if record is None:
            return None
        records.append(record)
    return records


def _file_record_from_cache_value(value: object) -> FileRecord | None:
    if not isinstance(value, tuple) or len(value) != FILE_RECORD_CACHE_FIELD_COUNT:
        return None
    (
        path,
        language,
        size_bytes,
        line_count,
        content_hash,
        role,
        is_generated,
        is_vendor,
        is_test,
        is_build_output,
    ) = value
    if not isinstance(path, str) or not isinstance(language, str):
        return None
    if not isinstance(size_bytes, int) or not isinstance(line_count, int):
        return None
    if not isinstance(content_hash, str) or not isinstance(role, str):
        return None
    return FileRecord(
        path=path,
        language=language,
        size_bytes=size_bytes,
        line_count=line_count,
        content_hash=content_hash,
        role=role,
        is_generated=is_generated is True,
        is_vendor=is_vendor is True,
        is_test=is_test is True,
        is_build_output=is_build_output is True,
    )


def _strings_from_cache_value(value: object) -> list[str] | None:
    if not isinstance(value, tuple) or not all(isinstance(item, str) for item in value):
        return None
    return list(value)


def _manifest_cache_value(manifest: RepositoryManifest) -> ManifestCacheValue:
    return (manifest.path, manifest.kind)


def _manifests_from_cache_value(value: object) -> tuple[RepositoryManifest, ...] | None:
    if not isinstance(value, tuple):
        return None
    manifests: list[RepositoryManifest] = []
    for item in value:
        manifest = _manifest_from_cache_value(item)
        if manifest is None:
            return None
        manifests.append(manifest)
    return tuple(manifests)


def _manifest_from_cache_value(value: object) -> RepositoryManifest | None:
    if not isinstance(value, tuple) or len(value) != MANIFEST_CACHE_FIELD_COUNT:
        return None
    path, kind = value
    if not isinstance(path, str) or not isinstance(kind, str):
        return None
    return RepositoryManifest(path=path, kind=kind)


__all__ = [
    "RepositoryFacts",
    "build_repository_facts",
    "repository_facts_cache_value",
    "repository_facts_from_cache_value",
]
