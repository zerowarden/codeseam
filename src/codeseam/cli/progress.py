from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from types import TracebackType

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TaskID, TextColumn

from codeseam.cli.models import OutputOptions
from codeseam.pipeline.progress import ProgressStage

PROGRESS_DONE_MARK = "✓"


class RichAnalysisProgress:
    def __init__(self, *, console: Console, enabled: bool) -> None:
        self._progress: Progress | None = (
            Progress(
                SpinnerColumn(finished_text=PROGRESS_DONE_MARK),
                TextColumn("{task.description}"),
                console=console,
                transient=True,
            )
            if enabled
            else None
        )

    def __enter__(self) -> RichAnalysisProgress:
        if self._progress:
            self._progress.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._progress:
            self._progress.__exit__(exc_type, exc, traceback)

    @contextmanager
    def stage(self, description: str) -> Iterator[ProgressStage]:
        task_id: TaskID | None = None
        if self._progress:
            task_id = self._progress.add_task(description, total=1)
        stage = RichProgressStage(description)
        try:
            yield stage
        except BaseException:
            if self._progress and task_id is not None:
                self._progress.update(task_id, description=f"{description} failed")
            raise
        else:
            if self._progress and task_id is not None:
                self._progress.update(task_id, description=stage.description)
                self._progress.update(task_id, completed=1)


@dataclass
class RichProgressStage:
    description: str

    def finish(self, message: str) -> None:
        self.description = message


def progress_for(options: OutputOptions, console: Console) -> RichAnalysisProgress:
    enabled = (
        options.output_format is None
        and not options.quiet
        and (options.progress == "always" or (options.progress == "auto" and console.is_terminal))
    )
    return RichAnalysisProgress(console=console, enabled=enabled)


__all__ = ["RichAnalysisProgress", "RichProgressStage", "progress_for"]
