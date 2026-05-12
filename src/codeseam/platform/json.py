from __future__ import annotations

import json as stdlib_json
import os
from collections.abc import Callable, Iterable
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TextIO, cast

from codeseam.platform.files import sha256_text

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue] | object
type Json = dict[str, JsonValue]


def dumps_jsonable_stable(payload: object, *, pretty: bool = False) -> str:
    """Serialize data that is already JSON-compatible.

    Use this on hot artifact/cache paths after models have crossed an explicit
    JSON boundary. It intentionally skips generic Python-object conversion.
    """
    if pretty:
        return stdlib_json.dumps(payload, indent=2, sort_keys=True)
    return stdlib_json.dumps(payload, separators=(",", ":"), sort_keys=True)


def dumps_jsonable_fast(payload: object) -> str:
    return stdlib_json.dumps(payload, separators=(",", ":"))


def json_digest(payload: object) -> str:
    return sha256_text(dumps_jsonable_stable(payload))


def loads_json(text: str) -> JsonValue:
    return cast(JsonValue, stdlib_json.loads(text))


def load_jsonl_objects(path: Path, *, missing_ok: bool = False) -> list[Json]:
    if missing_ok and not path.exists():
        return []
    records: list[Json] = []
    for _, line in _iter_jsonl_lines(path):
        if not line:
            continue
        record = loads_json(line)
        if isinstance(record, dict):
            records.append(cast(Json, record))
    return records


def as_json_object(value: object) -> Json:
    return cast(Json, value) if isinstance(value, dict) else {}


def as_json_objects(values: object) -> list[Json]:
    if not isinstance(values, list):
        return []
    return [cast(Json, value) for value in values if isinstance(value, dict)]


def json_text(payload: Json, key: str, default: str = "") -> str:
    value = payload.get(key)
    if value is None:
        return default
    return str(value)


def json_text_list(payload: Json, key: str) -> list[str]:
    return _json_text_values(payload.get(key))


def json_text_keys(payload: Json, key: str) -> list[str]:
    return sorted(_json_text_values(payload.get(key)))


def _json_text_values(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    if isinstance(value, dict):
        return [str(item) for item in value]
    return []


def json_float(value: object, default: float = 0.0) -> float:
    if not isinstance(value, int | float | str):
        return default
    try:
        return float(value)
    except ValueError:
        return default


def json_int(value: object, default: int = 0) -> int:
    if isinstance(value, int | float):
        return int(value)
    if not isinstance(value, str):
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _iter_jsonl_lines(path: Path) -> Iterable[tuple[int, str]]:
    return enumerate(path.read_text(encoding="utf-8").splitlines(), 1)


def write_atomic(path: Path, text: str) -> None:
    _atomic_write(path, lambda file: file.write(text))


def write_jsonable_atomic(path: Path, payload: object, *, pretty: bool = False) -> None:
    write_atomic(path, dumps_jsonable_stable(payload, pretty=pretty) + "\n")


def write_jsonl_jsonable_atomic(path: Path, records: Iterable[object]) -> None:
    _atomic_write(path, lambda file: _write_jsonl_records(file, records))


def _write_jsonl_records(file: TextIO, records: Iterable[object]) -> None:
    for record in records:
        file.write(dumps_jsonable_fast(record))
        file.write("\n")


def _atomic_write(path: Path, writer: Callable[[TextIO], object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
            temp_path = Path(tmp.name)
            writer(cast(TextIO, tmp))
        os.replace(temp_path, path)
    except BaseException:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise
