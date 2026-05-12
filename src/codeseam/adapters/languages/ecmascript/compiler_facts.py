from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from codeseam.analysis import FileRecord, RepositoryFacts, RepositoryManifest
from codeseam.platform import sha256_text
from codeseam.semantics import SemanticProject

TYPESCRIPT_PROJECT_FACTS_SCHEMA = "codeseam.typescript_project_facts.v1"
TYPESCRIPT_CONFIG_MANIFEST = "typescript_config"
NODE_MANIFEST = "node"
JS_TS_LANGUAGES = frozenset({"TypeScript", "TSX", "JavaScript", "JSX"})
LOCKFILE_NAMES = frozenset({"package-lock.json", "pnpm-lock.yaml", "yarn.lock"})
PACKAGE_MANIFEST_NAMES = frozenset({"package.json"})


@dataclass(frozen=True, slots=True)
class TypeScriptProjectFacts:
    """Project-level JS/TS facts that make compiler enrichment cacheable.

    These facts are intentionally derived from `RepositoryFacts`, not by
    starting a compiler. Tree-sitter stays the portable base frontend. A later
    compiler host can use `cache_key` to decide whether project-level type facts
    are reusable for the same tsconfig/package/source fingerprint.
    """

    schema_version: str = TYPESCRIPT_PROJECT_FACTS_SCHEMA
    tsconfig_paths: tuple[str, ...] = ()
    cache_key: str = ""

    def semantic_projects(self) -> tuple[SemanticProject, ...]:
        if not self.cache_key:
            return ()
        return (
            SemanticProject(
                project_id=self.tsconfig_paths[0] if self.tsconfig_paths else "typescript_project",
                language="TypeScript",
                languages=tuple(sorted(JS_TS_LANGUAGES)),
                project_cache_key=self.cache_key,
                config_path=self.tsconfig_paths[0] if self.tsconfig_paths else "",
            ),
        )


def extract_typescript_project_facts(facts: RepositoryFacts) -> TypeScriptProjectFacts:
    """Return deterministic JS/TS project inputs without reading source files.

    The scanner has already paid for path classification and content hashes.
    Reusing those records keeps this enrichment O(repository records) and avoids
    a costly TypeScript compiler startup during ordinary analysis.
    """

    source_records = _source_records(facts.records)
    tsconfigs = _manifest_paths(facts.manifests, TYPESCRIPT_CONFIG_MANIFEST)
    package_manifests, lockfiles = _node_manifests(facts.manifests)
    return TypeScriptProjectFacts(
        tsconfig_paths=tsconfigs,
        cache_key=_project_cache_key(
            facts,
            tsconfigs=tsconfigs,
            package_manifests=package_manifests,
            lockfiles=lockfiles,
            source_records=source_records,
        ),
    )


def _source_records(records: tuple[FileRecord, ...]) -> tuple[FileRecord, ...]:
    return tuple(
        sorted(
            (record for record in records if record.language in JS_TS_LANGUAGES),
            key=lambda record: record.path,
        )
    )


def _manifest_paths(
    manifests: tuple[RepositoryManifest, ...],
    kind: str,
) -> tuple[str, ...]:
    return tuple(sorted(manifest.path for manifest in manifests if manifest.kind == kind))


def _node_manifests(
    manifests: tuple[RepositoryManifest, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    node_paths = _manifest_paths(manifests, NODE_MANIFEST)
    package_manifests = tuple(
        path for path in node_paths if Path(path).name in PACKAGE_MANIFEST_NAMES
    )
    lockfiles = tuple(path for path in node_paths if Path(path).name in LOCKFILE_NAMES)
    return package_manifests, lockfiles


def _project_cache_key(
    facts: RepositoryFacts,
    *,
    tsconfigs: tuple[str, ...],
    package_manifests: tuple[str, ...],
    lockfiles: tuple[str, ...],
    source_records: tuple[FileRecord, ...],
) -> str:
    rows = [TYPESCRIPT_PROJECT_FACTS_SCHEMA]
    rows.extend(_path_hash_rows("tsconfig", tsconfigs, facts))
    rows.extend(_path_hash_rows("package", package_manifests, facts))
    rows.extend(_path_hash_rows("lockfile", lockfiles, facts))
    rows.extend(
        f"source\0{record.path}\0{record.language}\0{record.content_hash}"
        for record in source_records
    )
    return sha256_text("\n".join(rows))


def _path_hash_rows(
    label: str,
    paths: tuple[str, ...],
    facts: RepositoryFacts,
) -> tuple[str, ...]:
    return tuple(
        f"{label}\0{path}\0{facts.records_by_path.get(path, _EMPTY_RECORD).content_hash}"
        for path in paths
    )


_EMPTY_RECORD = FileRecord(
    path="",
    language="",
    size_bytes=0,
    line_count=0,
    content_hash="",
    role="",
    is_generated=False,
    is_vendor=False,
    is_test=False,
    is_build_output=False,
)


__all__ = [
    "TYPESCRIPT_CONFIG_MANIFEST",
    "TypeScriptProjectFacts",
    "extract_typescript_project_facts",
]
