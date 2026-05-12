from __future__ import annotations

import argparse
import shutil

from codeseam.cache import cache_stats
from codeseam.cli.exit_codes import OK
from codeseam.cli.models import CliOutput, cli_output
from codeseam.config import load_config
from codeseam.platform import file_locks, runtime_lock_paths


def cache_stats_command(args: argparse.Namespace) -> CliOutput:
    del args
    config = load_config()
    payload = {
        **cache_stats(config.cache_path()),
        "enabled": config.cache_enabled,
        "audit_output_root": str(config.path("output", "root")),
        "audit_output_exists": config.path("output", "root").exists(),
    }
    return cli_output("json_payload", payload=payload, exit_code=OK)


def cache_clear_command(args: argparse.Namespace) -> CliOutput:
    del args
    config = load_config()
    cache_path = config.cache_path()
    with file_locks(runtime_lock_paths(config.path("output", "root"), cache_path)):
        if config.path("output", "root").exists():
            shutil.rmtree(config.path("output", "root"))
        if cache_path.exists():
            shutil.rmtree(cache_path)
    return cli_output("none", exit_code=OK)


__all__ = ["cache_clear_command", "cache_stats_command"]
