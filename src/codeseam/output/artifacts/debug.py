from __future__ import annotations

import gzip
import shutil
from pathlib import Path, PurePosixPath

from codeseam.platform import ArtifactVisibility, OutputPaths, dumps_jsonable_stable, sha256_bytes

STAGING_DIR = ".staging"


def staging_paths(paths: OutputPaths) -> OutputPaths:
    """A fresh staging root inside the (ownership-checked) output root."""

    staging = OutputPaths(paths.root / STAGING_DIR)
    if staging.root.exists():
        shutil.rmtree(staging.root)
    return staging


def publish_reports(staging: OutputPaths, paths: OutputPaths) -> None:
    """Replace the previous run's reports with a finished run's, entry by entry.

    Only artifact entries are touched, so anything else in the output root (the
    ownership marker, a cache configured inside it) survives. A run that fails
    before this point leaves the previous reports in place.
    """

    paths.ensure_phase0()
    for name in sorted(_artifact_entry_names(paths)):
        old, new = paths.root / name, staging.root / name
        if old.is_dir() and not old.is_symlink():
            shutil.rmtree(old)
        elif old.exists() or old.is_symlink():
            old.unlink()
        if new.exists():
            new.replace(old)


def _artifact_entry_names(paths: OutputPaths) -> set[str]:
    relpaths = [
        *paths.artifact_refs(ArtifactVisibility.PUBLIC).values(),
        *paths.artifact_refs(ArtifactVisibility.INTERNAL).values(),
    ]
    return {PurePosixPath(relpath).parts[0] for relpath in relpaths}


def write_debug_bundle_and_prune(
    paths: OutputPaths,
    *,
    write_bundle: bool,
) -> None:
    if not write_bundle:
        return
    _write_bundle(paths)
    _remove_internal_artifacts(paths)


def _write_bundle(paths: OutputPaths) -> None:
    artifacts = _bundle_candidates(paths)
    with gzip.open(paths.artifact("debug_bundle"), "wt", encoding="utf-8") as file:
        for line_number, path in enumerate(artifacts, 1):
            data = path.read_bytes()
            relative = paths.relative(path)
            file.write(
                dumps_jsonable_stable(
                    {
                        "artifact": relative,
                        "content_utf8": data.decode("utf-8", errors="replace"),
                        "line": line_number,
                        "size_bytes": len(data),
                        "content_sha256": sha256_bytes(data),
                    }
                )
                + "\n"
            )


def _bundle_candidates(paths: OutputPaths) -> list[Path]:
    candidates = {
        paths.root / relative
        for relative in paths.artifact_refs(ArtifactVisibility.INTERNAL).values()
        if (paths.root / relative).is_file()
    }
    candidates.update(
        path
        for directory in _intermediate_dirs(paths)
        if directory.exists()
        for path in directory.rglob("*")
        if path.is_file()
    )
    return sorted(candidates, key=paths.relative)


def _remove_internal_artifacts(paths: OutputPaths) -> None:
    for directory in _intermediate_dirs(paths):
        if directory.exists():
            shutil.rmtree(directory)
    for relative in paths.artifact_refs(ArtifactVisibility.INTERNAL).values():
        path = paths.root / relative
        if path.exists():
            path.unlink()


def _intermediate_dirs(paths: OutputPaths) -> tuple[Path, ...]:
    return (
        paths.directory("raw"),
        paths.directory("context"),
    )
