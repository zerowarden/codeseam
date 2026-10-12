from __future__ import annotations

from pathlib import Path

import pytest

import codeseam.pipeline.analyze as analyze_pipeline
from codeseam import cli
from codeseam.output.artifacts.debug import STAGING_DIR
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


def _analyse(repo: Path) -> int:
    return cli.main(["analyze", str(repo), "--quiet"])


def test_a_failed_run_keeps_the_previous_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "mod.py").write_text("def f(x):\n    return x\n", encoding="utf-8")
    assert _analyse(tmp_path) == cli.OK
    reports = OutputPaths(tmp_path / ".codeseam" / "reports")
    previous = reports.artifact("agent_summary").read_text(encoding="utf-8")

    def interrupted(*_: object, **__: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(analyze_pipeline, "build_report_artifacts", interrupted)
    assert _analyse(tmp_path) == cli.INTERRUPTED

    assert reports.artifact("agent_summary").read_text(encoding="utf-8") == previous
    assert not (reports.root / STAGING_DIR).exists()


def test_a_finished_run_replaces_stale_artifacts(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text("def f(x):\n    return x\n", encoding="utf-8")
    reports = OutputPaths(tmp_path / ".codeseam" / "reports")
    assert cli.main(["analyze", str(tmp_path), "--quiet", "--debug"]) == cli.OK
    assert reports.artifact("debug_bundle").exists()

    assert _analyse(tmp_path) == cli.OK

    assert not reports.artifact("debug_bundle").exists()
    assert reports.artifact("agent_summary").exists()
