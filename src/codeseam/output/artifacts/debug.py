from __future__ import annotations

import gzip
import shutil
from pathlib import Path

from codeseam.platform import ArtifactVisibility, OutputPaths, dumps_jsonable_stable, sha256_bytes


def reset_audit_output(paths: OutputPaths) -> None:
    for directory in (
        paths.directory("agent"),
        paths.directory("raw"),
        paths.directory("context"),
    ):
        if directory.exists():
            shutil.rmtree(directory)
    legacy_normalized = paths.root / "normalized"
    if legacy_normalized.exists():
        shutil.rmtree(legacy_normalized)
    legacy_evidence = paths.root / "evidence"
    if legacy_evidence.exists():
        shutil.rmtree(legacy_evidence)
    legacy_bundle = paths.root / "evidence.jsonl.gz"
    if legacy_bundle.exists():
        legacy_bundle.unlink()
    bundle = paths.artifact("debug_bundle")
    if bundle.exists():
        bundle.unlink()
    _remove_internal_artifacts(paths)


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
