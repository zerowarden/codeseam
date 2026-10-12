from pathlib import Path


def _write(path: Path, text: str) -> None:
    if not text:
        raise ValueError(f"refusing to write empty file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write(path: Path, text: str) -> None:
    if not text:
        raise ValueError(f"refusing to write empty file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
