from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path

import pytest

from codeseam import cli
from codeseam.analysis import FileRecord
from codeseam.cache import PersistentCache, persistent_cache
from codeseam.cli import OK


@pytest.fixture
def cache_root(tmp_path: Path) -> Path:
    return tmp_path / ".cache" / "codeseam"


@pytest.fixture
def cache_factory(cache_root: Path) -> Iterator[Callable[..., PersistentCache]]:
    opened: list[PersistentCache] = []

    def make(*, enabled: bool = True) -> PersistentCache:
        cache = persistent_cache(cache_root, enabled=enabled)
        opened.append(cache)
        return cache

    yield make

    for cache in reversed(opened):
        cache.close()


def write_agent_sidecar(root: Path, filename: str, records: list[dict[str, object]]) -> None:
    target_dir = root / ".codeseam" / "reports" / "agent"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / filename).write_text(
        "".join(f"{json.dumps(record, separators=(',', ':'))}\n" for record in records),
        encoding="utf-8",
    )


def run_cli(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    args: list[str],
    *,
    expected: int = OK,
    chdir: bool = True,
) -> None:
    if chdir:
        monkeypatch.chdir(root)
    assert cli.main(args) == expected


def repo_dir(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    return repo


def assert_contains(text: str, fragments: Sequence[str]) -> None:
    _assert_text_fragments(text, fragments, expected_present=True)


def assert_not_contains(text: str, fragments: Sequence[str]) -> None:
    _assert_text_fragments(text, fragments, expected_present=False)


def assert_paths_exist(root: Path, paths: Sequence[str]) -> None:
    _assert_paths(root, paths, expected_present=True)


def assert_paths_absent(root: Path, paths: Sequence[str]) -> None:
    _assert_paths(root, paths, expected_present=False)


def _assert_text_fragments(
    text: str,
    fragments: Sequence[str],
    *,
    expected_present: bool,
) -> None:
    _assert_items(
        fragments,
        present=lambda fragment: fragment in text,
        expected_present=expected_present,
        failure_heading=(
            "Missing expected output fragments:"
            if expected_present
            else "Unexpected output fragments:"
        ),
        context=f"\n\nActual output:\n{text}",
    )


def _assert_paths(root: Path, paths: Sequence[str], *, expected_present: bool) -> None:
    failure_heading = "Missing expected paths:" if expected_present else "Unexpected paths present:"
    _assert_items(
        paths,
        present=lambda path: (root / path).exists(),
        expected_present=expected_present,
        failure_heading=failure_heading,
        context=f"\n\nRoot: {root}",
    )


def _assert_items[T](
    items: Sequence[T],
    *,
    present: Callable[[T], bool],
    expected_present: bool,
    failure_heading: str,
    context: str,
) -> None:
    _assert_no_items(
        [item for item in items if present(item) is not expected_present],
        failure_heading=failure_heading,
        context=context,
    )


def _assert_no_items[T](items: Sequence[T], *, failure_heading: str, context: str) -> None:
    assert not items, failure_heading + "\n" + "\n".join(f"- {item}" for item in items) + context


def explain_command_error(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    records: list[dict[str, object]],
    args: list[str],
    expected: int,
) -> None:
    write_agent_sidecar(root, "analysis.jsonl", records)
    run_cli(root, monkeypatch, args, expected=expected)


def target_record(target_id: str) -> dict[str, object]:
    return {
        "target_id": target_id,
        "target_type": "file_module_concern",
        "title": "Shared signature shape fn(str)->str",
        "review_tier": "review_candidate",
        "review_score": 0.5,
        "evidence_strength": "strong",
        "evidence_classes": ["signature_shape"],
        "files": ["src/module.py"],
        "locations": [
            {
                "file": "src/module.py",
                "symbol": "build",
                "kind": "signature_shape",
                "start_line": 1,
                "end_line": 2,
            }
        ],
        "metrics": {"relation_kind_counts": {"body_identical": 1}},
    }


def file_record(
    path: str,
    *,
    content_hash: str = "sha256:test",
    role: str = "source",
    language: str = "Python",
    is_test: bool | None = None,
) -> FileRecord:
    return FileRecord(
        path=path,
        language=language,
        size_bytes=0,
        line_count=0,
        content_hash=content_hash,
        role=role,
        is_generated=False,
        is_vendor=False,
        is_test=role == "test" if is_test is None else is_test,
        is_build_output=False,
    )
