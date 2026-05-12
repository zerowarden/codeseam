from __future__ import annotations

from pathlib import Path

from codeseam.platform import ARTIFACTS, ArtifactVisibility, OutputPaths


def test_output_paths_are_derived_from_artifact_registry(tmp_path: Path) -> None:
    paths = OutputPaths(tmp_path)
    public_refs = paths.artifact_refs()
    internal_refs = paths.artifact_refs(visibility=ArtifactVisibility.INTERNAL)

    assert public_refs == {
        artifact.key: artifact.relpath.as_posix()
        for artifact in ARTIFACTS
        if artifact.visibility == ArtifactVisibility.PUBLIC
    }
    assert internal_refs["findings"] == "findings.jsonl"
    assert paths.artifact("agent_summary") == tmp_path / "agent" / "summary.md"
    assert paths.artifact("findings") == tmp_path / "findings.jsonl"


def test_ensure_audit_uses_registry_directories(tmp_path: Path) -> None:
    paths = OutputPaths(tmp_path)

    paths.ensure_audit()

    assert paths.directory("agent").exists()
    assert paths.directory("context").exists()
