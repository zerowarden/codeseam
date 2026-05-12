from __future__ import annotations

import argparse
from pathlib import Path

from codeseam.adapters.repository.root import detect_repo_root
from codeseam.cli.exit_codes import OK
from codeseam.cli.models import CliOutput, cli_output
from codeseam.config import load_config, materialize_init_config
from codeseam.platform import CODESEAMIGNORE_RESOURCE, project_file, resource_text


def init_command(args: argparse.Namespace) -> CliOutput:
    root = detect_repo_root(cwd=Path.cwd())
    created: list[Path] = []
    existing: list[Path] = []

    config_path = project_file(root, "config")
    if materialize_init_config(config_path):
        created.append(config_path)
    else:
        existing.append(config_path)

    ignore_path = project_file(root, "ignore")
    if not args.no_ignore:
        if ignore_path.exists():
            existing.append(ignore_path)
        else:
            ignore_path.write_text(resource_text(CODESEAMIGNORE_RESOURCE), encoding="utf-8")
            created.append(ignore_path)

    config = load_config(root)
    if args.create_dirs:
        for path in (config.path("output", "root"), config.cache_path()):
            if path.exists():
                existing.append(path)
            else:
                path.mkdir(parents=True, exist_ok=True)
                created.append(path)

    return cli_output(
        "init_result",
        root=root,
        report_root=config.path("output", "root"),
        created=created,
        existing=existing,
        exit_code=OK,
    )


__all__ = ["init_command"]
