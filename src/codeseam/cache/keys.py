from __future__ import annotations

from typing import Protocol

from codeseam.analysis import FileRecord, RepositoryScan
from codeseam.platform import Json, json_digest
from codeseam.version import (
    FILE_ANALYSIS_CACHE_KEY_SCHEMA_VERSION,
    FILE_ANALYSIS_CACHE_VERSION,
    REPOSITORY_FACTS_CACHE_KEY_SCHEMA,
)


class _LanguageAnalysisIdentity(Protocol):
    @property
    def language(self) -> str: ...

    @property
    def relative_path(self) -> str: ...

    @property
    def role(self) -> str: ...


def cache_key(payload: Json) -> str:
    return json_digest(payload)


def file_analysis_cache_key(namespace: str, parts: Json) -> Json:
    return {
        "schema_version": FILE_ANALYSIS_CACHE_KEY_SCHEMA_VERSION,
        "version": FILE_ANALYSIS_CACHE_VERSION,
        "namespace": namespace,
        **parts,
    }


def language_analysis_cache_key(
    namespace: str,
    context: _LanguageAnalysisIdentity,
    file_record: FileRecord,
    adapter_id: str,
) -> Json:
    return file_analysis_cache_key(
        namespace,
        {
            "adapter_id": adapter_id,
            "language": context.language,
            "path": context.relative_path,
            "role": context.role,
            "content_hash": file_record.content_hash,
        },
    )


def repository_facts_cache_key(scan: RepositoryScan, selection_config: object) -> str:
    return cache_key(
        {
            "schema_version": REPOSITORY_FACTS_CACHE_KEY_SCHEMA,
            "selection": selection_config if isinstance(selection_config, dict) else {},
            "records": [
                (
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
                for record in scan.records
            ],
            "selected_paths": list(scan.selected_paths),
            "manifests": [(manifest.path, manifest.kind) for manifest in scan.manifests],
        }
    )
