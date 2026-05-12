from __future__ import annotations

import argparse

from codeseam.cli.exit_codes import OK, REPOSITORY_CONTEXT_ERROR
from codeseam.cli.explain import ExplainRenderOptions, explain_source_lines, load_explain
from codeseam.cli.models import CliOutput, cli_output
from codeseam.config import load_config


def explain_command(args: argparse.Namespace) -> CliOutput:
    config = load_config()
    item = load_explain(config, args.target_id)
    if item is None:
        return cli_output(
            "explain_not_found",
            target_id=args.target_id,
            exit_code=REPOSITORY_CONTEXT_ERROR,
        )
    top = max(1, int(args.top))
    show_source = bool(args.source or getattr(args, "verbose", False))
    return cli_output(
        "explain_result",
        item=item,
        options=ExplainRenderOptions(
            json_output=bool(args.json),
            full=bool(args.full),
            source=show_source,
            evidence=bool(args.evidence),
            pairs=bool(args.pairs),
            top=top,
        ),
        source_lines=explain_source_lines(item, config.repo_root, top) if show_source else None,
        exit_code=OK,
    )


__all__ = ["explain_command"]
