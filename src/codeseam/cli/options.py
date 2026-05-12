from __future__ import annotations

from pathlib import Path
from typing import Any

from codeseam.cli.models import OutputOptions


def output_options(args: Any) -> OutputOptions:
    ci = bool(getattr(args, "ci", False))
    output = getattr(args, "output", None)
    explicit_format = getattr(args, "format", None)
    output_format = explicit_format or ("json" if output else None)
    progress = "never" if ci or getattr(args, "no_progress", False) else str(args.progress)
    return OutputOptions(
        output_format=output_format,
        output=Path(output) if output else None,
        quiet=bool(args.quiet),
        verbose=bool(args.verbose),
        color="never" if ci else str(args.color),
        progress=progress,
        timings=bool(args.timings),
        target_limit=max(0, int(args.target_limit)),
        ci=ci,
    )


__all__ = ["output_options"]
