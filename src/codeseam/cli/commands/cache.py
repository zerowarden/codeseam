from __future__ import annotations

import argparse
import shutil

from codeseam.adapters.repository.root import detect_repo_root
from codeseam.cache import cache_stats
from codeseam.cli.exit_codes import OK
from codeseam.cli.models import CliOutput, cli_output
from codeseam.config import Config, load_config
from codeseam.platform import file_locks, runtime_lock_paths


def cache_stats_command(args: argparse.Namespace) -> CliOutput:
    del args
    config = load_config(detect_repo_root())
    payload = {
        **cache_stats(config.cache_path),
        "enabled": config.cache_enabled,
        "audit_output_root": str(config.output_root),
        "audit_output_exists": config.output_root.exists(),
    }
    return cli_output("json_payload", payload=payload, exit_code=OK)


def cache_clear_command(args: argparse.Namespace) -> CliOutput:
    del args
    clear_persistent_cache(load_config(detect_repo_root()))
    return cli_output("none", exit_code=OK)


def clear_persistent_cache(config: Config) -> None:
    """Delete the validated cache root under the analysis locks; reports are kept."""

    cache_path = config.cache_path
    with file_locks(runtime_lock_paths(config.output_root, cache_path)):
        if cache_path.exists():
            shutil.rmtree(cache_path)


__all__ = ["cache_clear_command", "cache_stats_command", "clear_persistent_cache"]
