import os
from pathlib import Path
from tempfile import NamedTemporaryFile


def write_atomic(path: Path, text: str) -> None:
    if not text:
        raise ValueError(f"refusing to write empty file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        tmp.write(text)
        temp_name = tmp.name
    os.replace(temp_name, path)
