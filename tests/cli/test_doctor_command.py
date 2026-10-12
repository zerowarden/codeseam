"""`codeseam doctor` checks that an analysis can run, without running one."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from codeseam import cli
from codeseam.cli.exit_codes import OK, USER_INPUT_ERROR


def _doctor(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    expected: int = OK,
) -> dict[str, object]:
    monkeypatch.chdir(repo)
    assert cli.main(["doctor", "--json"]) == expected
    return cast(dict[str, object], json.loads(capsys.readouterr().out))


def _statuses(payload: dict[str, object]) -> dict[str, str]:
    checks = payload["checks"]
    assert isinstance(checks, list)
    return {f"{check['area']}/{check['name']}": check["status"] for check in checks}


def _repo(tmp_path: Path, config: str = "", **files: str) -> Path:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    if config:
        (tmp_path / "codeseam.toml").write_text(config, encoding="utf-8")
    for name, source in (files or {"src/app.py": "def run(x):\n    return x\n"}).items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    return tmp_path


def test_a_healthy_repository_passes_every_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = _doctor(_repo(tmp_path), monkeypatch, capsys)
    statuses = _statuses(payload)

    assert payload["schema_version"] == "codeseam.doctor.v1"
    assert "fail" not in statuses.values()
    assert statuses["config/configuration"] == "ok"
    assert all(statuses[f"parsers/{language}"] == "ok" for language in ("Python", "TypeScript"))
    assert statuses["selection/files to analyse"] == "ok"
    assert payload["settings"]["output.root"] == ".codeseam/reports"  # type: ignore[index]


@pytest.mark.parametrize(
    ("config", "files", "check", "status", "exit_code"),
    [
        ("[output]\nroot = 5\n", {}, "config/configuration", "fail", USER_INPUT_ERROR),
        ("", {"README.md": "# demo\n"}, "selection/files to analyse", "warn", OK),
        ('[semantics]\nmode = "project"\n', {}, "semantics/trust", "warn", OK),
    ],
    ids=["bad-config", "nothing-to-analyse", "untrusted-provider"],
)
def test_problems_are_reported_with_their_status(  # noqa: PLR0913
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    config: str,
    files: dict[str, str],
    check: str,
    status: str,
    exit_code: int,
) -> None:
    payload = _doctor(_repo(tmp_path, config, **files), monkeypatch, capsys, exit_code)

    assert _statuses(payload)[check] == status


def test_an_unowned_output_root_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path)
    (repo / "codeseam.toml").write_text('[output]\nroot = "own"\n', encoding="utf-8")
    (repo / "own").mkdir()
    (repo / "own" / "notes.txt").write_text("mine\n", encoding="utf-8")

    payload = _doctor(repo, monkeypatch, capsys, USER_INPUT_ERROR)
    checks = cast(list[dict[str, str]], payload["checks"])

    assert _statuses(payload)["config/configuration"] == "fail"
    assert any("not managed by Codeseam" in check["detail"] for check in checks)


def test_doctor_never_starts_the_semantic_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def refuse(*args: object, **kwargs: object) -> object:
        raise AssertionError("doctor started a process for the semantic worker")

    monkeypatch.setattr("codeseam.semantics.transport.StdioSemanticProvider.enrich", refuse)
    monkeypatch.setattr("codeseam.semantics.worker.typescript_provider", refuse)
    config = '[semantics]\nmode = "project"\ntrust_project_code = true\n'
    repo = _repo(tmp_path, config, **{"src/app.ts": "export function run(x) { return x; }\n"})
    package = repo / "node_modules" / "typescript" / "package.json"
    package.parent.mkdir(parents=True)
    package.write_text('{"version": "5.6.0"}', encoding="utf-8")

    statuses = _statuses(_doctor(repo, monkeypatch, capsys))

    assert statuses["semantics/trust"] == "ok"
    assert statuses["semantics/typescript package"] == "ok"


def test_text_output_groups_checks_by_area(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(_repo(tmp_path))

    assert cli.main(["doctor"]) == OK
    text = capsys.readouterr().out

    assert "Codeseam doctor:" in text
    assert "Parsers" in text
    assert "0 failed" in text
