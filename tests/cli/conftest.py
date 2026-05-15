from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest
from helpers import run_cli, write_agent_sidecar

from codeseam.cli import OK

from .fixtures import CliResult, CliRunner, SidecarWriter

APP_SOURCE = "def app() -> int:\n    return 1\n"


@pytest.fixture
def cli_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> CliRunner:
    def run(args: Sequence[str], *, expected: int = OK) -> CliResult:
        run_cli(tmp_path, monkeypatch, list(args), expected=expected)
        captured = capsys.readouterr()
        return CliResult(stdout=captured.out, stderr=captured.err)

    return run


@pytest.fixture
def cwd_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def app_repo(cwd_repo: Path) -> Path:
    source = cwd_repo / "src" / "app.py"
    source.parent.mkdir(exist_ok=True)
    source.write_text(APP_SOURCE, encoding="utf-8")
    return cwd_repo


@pytest.fixture
def sidecar_writer(cwd_repo: Path) -> SidecarWriter:
    def write(sidecar: str, records: list[dict[str, object]]) -> None:
        write_agent_sidecar(cwd_repo, sidecar, records)

    return write
