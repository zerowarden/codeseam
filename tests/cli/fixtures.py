from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from codeseam.cli import OK


@dataclass(frozen=True, slots=True)
class CliResult:
    stdout: str
    stderr: str


class CliRunner(Protocol):
    def __call__(self, args: Sequence[str], *, expected: int = OK) -> CliResult: ...


class SidecarWriter(Protocol):
    def __call__(self, sidecar: str, records: list[dict[str, object]]) -> None: ...
