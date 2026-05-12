from __future__ import annotations

from collections import Counter
from typing import Any

from codeseam.analysis import FileRecord, RepositoryManifest
from codeseam.platform import Json


def file_record_payload(record: FileRecord) -> Json:
    return {
        "path": record.path,
        "language": record.language,
        "size_bytes": record.size_bytes,
        "line_count": record.line_count,
        "content_hash": record.content_hash,
        "role": record.role,
        "is_generated": record.is_generated,
        "is_vendor": record.is_vendor,
        "is_test": record.is_test,
        "is_build_output": record.is_build_output,
    }


def repository_summary_payload(
    kind: str,
    records: list[FileRecord],
    selected_paths: list[str],
) -> Json:
    payload: Json = {
        "schema_version": f"codeseam.{kind}_summary.v1",
        **_summary_counts(records, selected_paths),
    }
    match kind:
        case "file":
            payload["by_language"] = dict(Counter(record.language for record in records))
            payload["by_role"] = dict(Counter(record.role for record in records))
        case "repo":
            payload["repo_root"] = "."
            payload["has_tests"] = any(record.is_test for record in records)
            payload["languages"] = sorted({record.language for record in records})
        case _:
            raise ValueError(f"Unknown repository summary kind: {kind}")
    return payload


def repository_manifests_payload(manifests: tuple[RepositoryManifest, ...]) -> dict[str, Any]:
    found = [{"path": manifest.path, "kind": manifest.kind} for manifest in manifests]
    return {"schema_version": "codeseam.manifests.v1", "repo_root": ".", "manifests": found}


def _summary_counts(records: list[FileRecord], selected_paths: list[str]) -> dict[str, int]:
    return {
        "file_count": len(records),
        "selected_file_count": len(selected_paths),
    }
