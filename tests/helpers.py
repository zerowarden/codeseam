from __future__ import annotations

import json
from pathlib import Path

import pytest

from codeseam import cli
from codeseam.analysis import FileRecord
from codeseam.cli import OK


def write_agent_sidecar(root: Path, filename: str, records: list[dict[str, object]]) -> None:
    target_dir = root / ".codeseam" / "reports" / "agent"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / filename).write_text(
        "".join(f"{json.dumps(record, separators=(',', ':'))}\n" for record in records),
        encoding="utf-8",
    )


def run_cli(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    args: list[str],
    *,
    expected: int = OK,
    chdir: bool = True,
) -> None:
    if chdir:
        monkeypatch.chdir(root)
    assert cli.main(args) == expected


def run_cli_output(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    args: list[str],
    *,
    expected: int = OK,
) -> str:
    run_cli(root, monkeypatch, args, expected=expected)
    return capsys.readouterr().out


def repo_dir(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    return repo


def assert_contains(text: str, fragments: list[str]) -> None:
    for fragment in fragments:
        assert fragment in text


def assert_paths_exist(root: Path, paths: list[str]) -> None:
    for path in paths:
        assert (root / path).exists()


def explain_command_error(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    records: list[dict[str, object]],
    args: list[str],
    expected: int,
) -> None:
    write_agent_sidecar(root, "analysis.jsonl", records)
    run_cli(root, monkeypatch, args, expected=expected)


def target_record(target_id: str) -> dict[str, object]:
    return {
        "target_id": target_id,
        "target_type": "file_module_concern",
        "title": "Shared signature shape fn(str)->str",
        "review_tier": "review_candidate",
        "review_score": 0.5,
        "evidence_strength": "strong",
        "evidence_classes": ["signature_shape"],
        "files": ["src/module.py"],
        "locations": [
            {
                "file": "src/module.py",
                "symbol": "build",
                "kind": "signature_shape",
                "start_line": 1,
                "end_line": 2,
            }
        ],
        "metrics": {"relation_kind_counts": {"body_identical": 1}},
    }


def file_record(
    path: str,
    *,
    content_hash: str = "sha256:test",
    role: str = "source",
    language: str = "Python",
    is_test: bool | None = None,
) -> FileRecord:
    return FileRecord(
        path=path,
        language=language,
        size_bytes=0,
        line_count=0,
        content_hash=content_hash,
        role=role,
        is_generated=False,
        is_vendor=False,
        is_test=role == "test" if is_test is None else is_test,
        is_build_output=False,
    )
