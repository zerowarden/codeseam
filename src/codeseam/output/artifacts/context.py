from __future__ import annotations

from codeseam.analysis import FileRecord, RepositoryManifest
from codeseam.output.serializers.repository import (
    file_record_payload,
    repository_manifests_payload,
    repository_summary_payload,
)
from codeseam.platform import (
    OutputPaths,
    write_atomic,
    write_jsonable_atomic,
    write_jsonl_jsonable_atomic,
)


def write_context_artifacts(
    paths: OutputPaths,
    records: list[FileRecord],
    selected_paths: list[str],
    manifests: tuple[RepositoryManifest, ...],
) -> None:
    write_atomic(
        paths.artifact("selected_files"),
        "\n".join(selected_paths) + "\n",
    )
    write_jsonl_jsonable_atomic(
        paths.artifact("files"),
        [file_record_payload(record) for record in records],
    )
    write_jsonable_atomic(
        paths.artifact("file_summary"),
        repository_summary_payload("file", records, selected_paths),
        pretty=True,
    )
    write_jsonable_atomic(
        paths.artifact("repo_summary"),
        repository_summary_payload("repo", records, selected_paths),
        pretty=True,
    )
    write_jsonable_atomic(
        paths.artifact("manifests"),
        repository_manifests_payload(manifests),
        pretty=True,
    )
