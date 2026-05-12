from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Protocol


class ProgressStage(Protocol):
    def finish(self, message: str) -> None: ...


class ProgressReporter(Protocol):
    def stage(self, description: str) -> AbstractContextManager[ProgressStage]: ...


__all__ = ["ProgressReporter", "ProgressStage"]
