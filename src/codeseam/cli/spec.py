from __future__ import annotations

from typing import Any

from codeseam.cli.constants import ANALYZE_FORMATS, DEFAULT_PAIR_LIMIT, DEFAULT_TARGET_LIMIT

type ArgumentSpec = dict[str, Any]
type CommandSpec = dict[str, Any]


def command_specs() -> dict[str, CommandSpec]:
    return {
        "init": {
            "description": "Create a small codeseam.toml and optional local files.",
            "help": "Initialize Codeseam config for this repository.",
            "handler": "init",
            "arguments": (
                {
                    "names": ("--no-ignore",),
                    "action": "store_true",
                    "help": "Do not create .codeseamignore.",
                },
                {
                    "names": ("--create-dirs",),
                    "action": "store_true",
                    "help": "Create report and cache directories.",
                },
            ),
        },
        "analyze": {
            "description": "Analyze a repository and write compact agent report artifacts.",
            "help": "Analyze a repository for refactor opportunities.",
            "handler": "analyze",
            "arguments": (
                {"names": ("path",), "nargs": "?", "help": "Repository path to analyze."},
                {"names": ("--repo-root",), "help": "Repository root override."},
                {
                    "names": ("--base",),
                    "dest": "base_ref",
                    "help": "Base git ref for changed-file scope.",
                },
                {"names": ("--since",), "dest": "base_ref", "help": "Alias for --base."},
                {
                    "names": ("--strict",),
                    "action": "store_true",
                    "help": "Exit non-zero on high findings.",
                },
                {
                    "names": ("--ci",),
                    "action": "store_true",
                    "help": "Run in CI mode: JSON output, no color, no progress, compact logs.",
                },
                {
                    "names": ("--debug",),
                    "action": "store_true",
                    "help": "Write compressed full evidence details for debugging.",
                },
                {
                    "names": ("--semantic-mode",),
                    "choices": ("off", "auto", "project", "required"),
                    "help": "Optional semantic provider mode.",
                },
                {
                    "names": ("--show-exclusions",),
                    "action": "store_true",
                    "help": "Print default exclusions.",
                },
                {"names": ("--include",), "action": "append", "help": "Include pattern."},
                {"names": ("--exclude",), "action": "append", "help": "Exclude pattern."},
                {
                    "names": ("--explain-files",),
                    "action": "store_true",
                    "help": "Explain analyzed/skipped files.",
                },
                {"names": ("--format",), "choices": ANALYZE_FORMATS, "help": "Output format."},
                {"names": ("--output",), "help": "Write machine output to this path."},
                {"names": ("--quiet",), "action": "store_true", "help": "Suppress output."},
                {"names": ("--verbose",), "action": "store_true", "help": "Print more detail."},
                {
                    "names": ("--color",),
                    "choices": ("auto", "always", "never"),
                    "default": "auto",
                    "help": "Color output mode.",
                },
                {
                    "names": ("--progress",),
                    "choices": ("auto", "always", "never"),
                    "default": "auto",
                    "help": "Progress display mode.",
                },
                {
                    "names": ("--no-progress",),
                    "action": "store_true",
                    "help": "Disable progress display.",
                },
                {"names": ("--timings",), "action": "store_true", "help": "Include timings."},
                {
                    "names": ("--target-limit",),
                    "type": int,
                    "default": DEFAULT_TARGET_LIMIT,
                    "help": "Target limit.",
                },
            ),
        },
        "profile": {
            "description": "Run analysis under cProfile for local development.",
            "help": "Profile an analysis run.",
            "handler": "profile",
            "arguments": (
                {"names": ("--repo-root",), "help": "Repository root override."},
                {
                    "names": ("--cold",),
                    "action": "store_const",
                    "const": "cold",
                    "dest": "cache_mode",
                    "help": "Clear the persistent cache before profiling.",
                },
                {
                    "names": ("--cache-mode",),
                    "choices": ("warm", "cold"),
                    "default": "warm",
                    "help": "Persistent cache mode for the profiled run.",
                },
                {"names": ("--limit",), "type": int, "default": 30, "help": "Profiler rows."},
                {"names": ("--sort",), "default": "cumtime", "help": "pstats sort key."},
            ),
        },
        "explain": {
            "description": "Show a compact target summary with optional detail.",
            "help": "Explain one review target.",
            "handler": "explain",
            "arguments": (
                {"names": ("target_id",), "help": "Stable target id."},
                {"names": ("--json",), "action": "store_true", "help": "Print JSON."},
                {"names": ("--full",), "action": "store_true", "help": "Print full JSON."},
                {"names": ("--verbose",), "action": "store_true", "help": "Show source snippets."},
                {"names": ("--source",), "action": "store_true", "help": "Show source snippets."},
                {"names": ("--evidence",), "action": "store_true", "help": "Show evidence."},
                {"names": ("--pairs",), "action": "store_true", "help": "Show relation pairs."},
                {"names": ("--top",), "type": int, "default": DEFAULT_PAIR_LIMIT, "help": "Limit."},
            ),
        },
        "cache": {
            "description": "Show or clear Codeseam's persistent analysis cache.",
            "help": "Show cache stats or clear cache data.",
            "handler": "cache_stats",
            "subcommand_dest": "cache_command",
            "subcommands": {
                "clear": {
                    "description": "Clear persistent analysis cache data.",
                    "help": "Clear persistent analysis cache data.",
                    "handler": "cache_clear",
                },
            },
        },
    }
