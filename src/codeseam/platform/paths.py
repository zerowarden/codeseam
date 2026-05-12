from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath

PROJECT_DIR = ".codeseam"
PROJECT_CONFIG = "codeseam.toml"
PROJECT_IGNORE = ".codeseamignore"
DEFAULT_OUTPUT_ROOT = PurePosixPath(PROJECT_DIR, "reports")
DEFAULT_CACHE_ROOT = PurePosixPath(PROJECT_DIR, "cache")
RUNTIME_LOCK_DIR = PurePosixPath(PROJECT_DIR, "runtime", "locks")
PROJECT_FILE_REFS = {
    "config": PROJECT_CONFIG,
    "ignore": PROJECT_IGNORE,
}

DIRECTORY_REFS = {
    "agent": PurePosixPath("agent"),
    "raw": PurePosixPath("raw"),
    "context": PurePosixPath("context"),
}


class ArtifactVisibility(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"


@dataclass(frozen=True)
class ArtifactPath:
    key: str
    relpath: PurePosixPath
    visibility: ArtifactVisibility


PUBLIC = ArtifactVisibility.PUBLIC
INTERNAL = ArtifactVisibility.INTERNAL

ARTIFACTS = (
    ArtifactPath("manifest", PurePosixPath("manifest.json"), PUBLIC),
    ArtifactPath("meta_readme", PurePosixPath("README.md"), PUBLIC),
    ArtifactPath("agent_summary", PurePosixPath("agent/summary.md"), PUBLIC),
    ArtifactPath(
        "agent_analysis",
        PurePosixPath("agent/analysis.jsonl"),
        PUBLIC,
    ),
    ArtifactPath("agent_observations", PurePosixPath("agent/observations.jsonl"), PUBLIC),
    ArtifactPath("agent_metrics", PurePosixPath("agent/metrics.json"), PUBLIC),
    ArtifactPath("selected_files", PurePosixPath("raw/selected_files.txt"), INTERNAL),
    ArtifactPath("files", PurePosixPath("context/files.jsonl"), INTERNAL),
    ArtifactPath("file_summary", PurePosixPath("context/file_summary.json"), INTERNAL),
    ArtifactPath("repo_summary", PurePosixPath("context/repo_summary.json"), INTERNAL),
    ArtifactPath("manifests", PurePosixPath("context/manifests.json"), INTERNAL),
    ArtifactPath("functions", PurePosixPath("functions.jsonl"), INTERNAL),
    ArtifactPath(
        "function_inventory_summary",
        PurePosixPath("function_inventory_summary.json"),
        INTERNAL,
    ),
    ArtifactPath("signatures", PurePosixPath("signatures.jsonl"), INTERNAL),
    ArtifactPath(
        "signature_clusters",
        PurePosixPath("signature_clusters.json"),
        INTERNAL,
    ),
    ArtifactPath("findings", PurePosixPath("findings.jsonl"), INTERNAL),
    ArtifactPath("debug_bundle", PurePosixPath("debug.jsonl.gz"), PUBLIC),
)

ARTIFACT_RELPATHS = {artifact.key: artifact.relpath for artifact in ARTIFACTS}


def _refs_for(visibility: ArtifactVisibility) -> dict[str, str]:
    return {
        artifact.key: artifact.relpath.as_posix()
        for artifact in ARTIFACTS
        if artifact.visibility == visibility
    }


_ARTIFACT_REFS_BY_VISIBILITY = {
    visibility: _refs_for(visibility) for visibility in ArtifactVisibility
}

ARTIFACT_REFS = _ARTIFACT_REFS_BY_VISIBILITY[PUBLIC]

AGENT_SUMMARY = ARTIFACT_REFS["agent_summary"]


def _known[T](mapping: dict[str, T], key: str, label: str) -> T:
    try:
        return mapping[key]
    except KeyError as exc:
        known = ", ".join(sorted(mapping))
        raise KeyError(f"Unknown {label} {key!r}. Known {label}s: {known}") from exc


def _resolve_path(
    root: Path,
    refs: dict[str, PurePosixPath],
    key: str,
    label: str,
) -> Path:
    return root / Path(_known(refs, key, label))


@dataclass(frozen=True)
class OutputPaths:
    root: Path

    def artifact(self, key: str) -> Path:
        return _resolve_path(self.root, ARTIFACT_RELPATHS, key, "artifact")

    def directory(self, key: str) -> Path:
        relpath = _known(DIRECTORY_REFS, key, "directory")
        return self.root / Path(relpath)

    def relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def artifact_refs(self, visibility: ArtifactVisibility = PUBLIC) -> dict[str, str]:
        return dict(_ARTIFACT_REFS_BY_VISIBILITY[visibility])

    def ensure_phase0(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def ensure_audit(self, *, include_internal: bool = True) -> None:
        self.ensure_phase0()
        dirs = {
            artifact.relpath.parent
            for artifact in ARTIFACTS
            if artifact.relpath.parent != PurePosixPath(".")
            and (include_internal or artifact.visibility == ArtifactVisibility.PUBLIC)
        }
        for rel_dir in sorted(dirs, key=str):
            (self.root / Path(rel_dir)).mkdir(parents=True, exist_ok=True)


def config_candidates(repo_root: Path) -> tuple[Path, Path]:
    return project_file(repo_root, "config"), project_path(repo_root, PROJECT_DIR, PROJECT_CONFIG)


def project_path(repo_root: Path, *parts: str) -> Path:
    return repo_root.joinpath(*parts)


def project_file(repo_root: Path, key: str) -> Path:
    return project_path(repo_root, _known(PROJECT_FILE_REFS, key, "project file"))


def display_path(root: Path, path: Path) -> str:
    try:
        value = path.relative_to(root).as_posix()
    except ValueError:
        value = path.as_posix()
    return value or "."


def path_parts(path: str) -> list[str]:
    return path.split("/") if path else [""]


def parent_path(path: str) -> str:
    return "/".join(path_parts(path)[:-1])


def basename(path: str) -> str:
    return path_parts(path)[-1]


def runtime_lock_paths(output_root: Path, cache_root: Path) -> tuple[Path, Path]:
    lock_dir = runtime_lock_dir(output_root, cache_root)
    return lock_dir / "analyze.lock", lock_dir / "cache.lock"


def runtime_lock_dir(output_root: Path, cache_root: Path) -> Path:
    """Stable runtime lock location for a Codeseam run.

    Lock files are persistent rendezvous files for flock-style locking. Keeping
    them under `.codeseam/runtime` avoids mixing process coordination files with
    reports or persistent cache payloads.
    """

    return _runtime_root(output_root, cache_root) / Path(RUNTIME_LOCK_DIR.relative_to(PROJECT_DIR))


def _runtime_root(output_root: Path, cache_root: Path) -> Path:
    for root in (output_root, cache_root):
        project_dir = _nearest_project_dir(root)
        if project_dir is not None:
            return project_dir

    common_parent = Path(
        os.path.commonpath(
            [
                str(output_root.resolve(strict=False).parent),
                str(cache_root.resolve(strict=False).parent),
            ]
        )
    )
    if common_parent.parent == common_parent:
        common_parent = output_root.resolve(strict=False).parent
    return common_parent / PROJECT_DIR


def _nearest_project_dir(path: Path) -> Path | None:
    resolved = path.resolve(strict=False)
    for item in (resolved, *resolved.parents):
        if item.name == PROJECT_DIR:
            return item
    return None
