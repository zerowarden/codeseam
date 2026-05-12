from __future__ import annotations

from codeseam.adapters.languages import ManifestMatcher, matching_manifest_kind
from codeseam.analysis import FileRecord, RepositoryManifest

REPOSITORY_MANIFEST_MATCHERS = (
    ManifestMatcher("vcs", (".gitignore",)),
    ManifestMatcher("pre_commit", (".pre-commit-config.yaml",)),
)


def discover_repository_manifests(
    records: list[FileRecord],
    language_matchers: tuple[ManifestMatcher, ...],
) -> tuple[RepositoryManifest, ...]:
    matchers = (*language_matchers, *REPOSITORY_MANIFEST_MATCHERS)
    return tuple(
        RepositoryManifest(path=record.path, kind=kind)
        for record in records
        if (kind := matching_manifest_kind(record.path, matchers)) is not None
    )


__all__ = ["REPOSITORY_MANIFEST_MATCHERS", "discover_repository_manifests"]
