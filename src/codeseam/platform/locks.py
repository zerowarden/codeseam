from __future__ import annotations

import fcntl
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import TracebackType
from typing import BinaryIO


class FileLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._file: BinaryIO | None = None

    def __enter__(self) -> FileLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("a+b")
        fcntl.flock(self._file.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback
        if self._file is not None:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
            self._file.close()
            self._file = None


@contextmanager
def file_locks(paths: tuple[Path, ...]) -> Iterator[None]:
    unique_paths = tuple(sorted(set(paths)))
    with ExitStack() as stack:
        for path in unique_paths:
            stack.enter_context(FileLock(path))
        yield


__all__ = ["FileLock", "file_locks"]
