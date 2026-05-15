from __future__ import annotations

from importlib import import_module

import pytest
from helpers import assert_contains

from codeseam import cli
from codeseam.cli import CONFIG_ERROR, INTERRUPTED

EXPECTED_TARGET_TOP = 2


@pytest.mark.parametrize(
    ("args", "attribute", "expected"),
    [
        pytest.param(["analyze"], "command", "analyze", id="analyze-command"),
        pytest.param(["analyze", "repo"], "path", "repo", id="analyze-positional-path"),
        pytest.param(["analyze", "--since", "main"], "base_ref", "main", id="analyze-since"),
        pytest.param(
            ["analyze", "--show-exclusions"],
            "show_exclusions",
            True,
            id="analyze-show-exclusions",
        ),
        pytest.param(
            ["analyze", "--include", "src/**/*.py"],
            "include",
            ["src/**/*.py"],
            id="analyze-include",
        ),
        pytest.param(
            ["analyze", "--exclude", "tests/**"],
            "exclude",
            ["tests/**"],
            id="analyze-exclude",
        ),
        pytest.param(
            ["analyze", "--explain-files"],
            "explain_files",
            True,
            id="analyze-explain-files",
        ),
        pytest.param(["analyze", "--format", "json"], "format", "json", id="analyze-json"),
        pytest.param(
            ["analyze", "--output", "out.json"],
            "output",
            "out.json",
            id="analyze-output",
        ),
        pytest.param(["analyze", "--quiet"], "quiet", True, id="analyze-quiet"),
        pytest.param(["analyze", "--verbose"], "verbose", True, id="analyze-verbose"),
        pytest.param(["analyze", "--color", "never"], "color", "never", id="analyze-color"),
        pytest.param(
            ["analyze", "--progress", "never"],
            "progress",
            "never",
            id="analyze-progress",
        ),
        pytest.param(["analyze", "--no-progress"], "no_progress", True, id="analyze-no-progress"),
        pytest.param(["analyze", "--ci"], "ci", True, id="analyze-ci"),
        pytest.param(["analyze", "--debug"], "debug", True, id="analyze-debug"),
        pytest.param(["analyze", "--timings"], "timings", True, id="analyze-timings"),
        pytest.param(["profile"], "command", "profile", id="profile-command"),
        pytest.param(["profile", "--cold"], "cache_mode", "cold", id="profile-cold"),
        pytest.param(
            ["profile", "--cache-mode", "warm"],
            "cache_mode",
            "warm",
            id="profile-warm",
        ),
        pytest.param(["init"], "command", "init", id="init-command"),
        pytest.param(["init", "--no-ignore"], "no_ignore", True, id="init-no-ignore"),
        pytest.param(
            ["init", "--create-dirs"],
            "create_dirs",
            True,
            id="init-create-dirs",
        ),
        pytest.param(["explain", "rt_000001"], "command", "explain", id="explain-command"),
        pytest.param(["explain", "rt_000001", "--json"], "json", True, id="explain-json"),
        pytest.param(["explain", "rt_000001", "--full"], "full", True, id="explain-full"),
        pytest.param(
            ["explain", "rt_000001", "--verbose"],
            "verbose",
            True,
            id="explain-verbose",
        ),
        pytest.param(
            ["explain", "rt_000001", "--source"],
            "source",
            True,
            id="explain-source",
        ),
        pytest.param(
            ["explain", "rt_000001", "--evidence"],
            "evidence",
            True,
            id="explain-evidence",
        ),
        pytest.param(["explain", "rt_000001", "--pairs"], "pairs", True, id="explain-pairs"),
        pytest.param(
            ["explain", "rt_000001", "--top", "2"],
            "top",
            EXPECTED_TARGET_TOP,
            id="explain-top",
        ),
        pytest.param(["cache"], "command", "cache", id="cache-command"),
        pytest.param(["cache", "clear"], "cache_command", "clear", id="cache-clear"),
    ],
)
def test_cli_parser_options(args: list[str], attribute: str, expected: object) -> None:
    parser = cli.build_parser()
    assert getattr(parser.parse_args(args), attribute) == expected


def test_main_handles_keyboard_interrupt(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def interrupt(args: object) -> int:
        del args
        raise KeyboardInterrupt

    main_module = import_module("codeseam.cli.main")
    monkeypatch.setattr(main_module, "analyze_command", interrupt)

    assert cli.main(["analyze"]) == INTERRUPTED
    assert "cancelled by user" in capsys.readouterr().err


def test_invalid_command_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["unknown"]) == CONFIG_ERROR

    output = capsys.readouterr()
    assert_contains(output.err, ["usage: codeseam", "analyze"])
