from __future__ import annotations

import argparse

from codeseam.adapters.repository.root import detect_repo_root
from codeseam.cli.commands.analyze import explicit_repo_root
from codeseam.cli.exit_codes import OK, USER_INPUT_ERROR
from codeseam.cli.models import CliOutput, cli_output
from codeseam.pipeline.doctor import run_doctor


def doctor_command(args: argparse.Namespace) -> CliOutput:
    """Check the environment and settings of a repository; exit 2 if a check fails."""

    report = run_doctor(detect_repo_root(explicit_repo_root(getattr(args, "path", None))))
    exit_code = USER_INPUT_ERROR if report.failed else OK
    if getattr(args, "json", False):
        return cli_output("json_payload", payload=report.payload(), exit_code=exit_code)
    return cli_output("doctor_result", report=report, exit_code=exit_code)


__all__ = ["doctor_command"]
