from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CliOutput:
    kind: str
    data: dict[str, Any] = field(default_factory=dict)
    exit_code: int = 0


@dataclass(frozen=True)
class OutputOptions:
    output_format: str | None
    output: Path | None
    quiet: bool
    verbose: bool
    color: str
    progress: str
    timings: bool
    target_limit: int
    ci: bool


def cli_output(kind: str, *, exit_code: int = 0, **data: Any) -> CliOutput:
    return CliOutput(kind=kind, data=data, exit_code=exit_code)


__all__ = ["CliOutput", "OutputOptions", "cli_output"]
