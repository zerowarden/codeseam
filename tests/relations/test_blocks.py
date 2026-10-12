"""Partial clones: a statement block shared by otherwise different functions."""

from __future__ import annotations

from pathlib import Path

import pytest

from codeseam.adapters.languages import LanguageAnalysisContext, default_language_registry
from codeseam.analysis.relations.blocks import member_identity, shared_blocks
from codeseam.analysis.signatures import SignatureCore
from codeseam.cache import signature_analyses_from_records

BLOCK = (
    "    source = Path(job.path)\n"
    "    if not source.exists():\n"
    "        raise FileNotFoundError(source)\n"
    "    settings = json.loads(job.settings)\n"
    "    size = int(settings.get('size', 1))\n"
    "    if size <= 0:\n"
    "        raise ValueError(size)\n"
    "    log.info('job %s', job.name)\n"
)


def _cores(tmp_path: Path, source: str, role: str = "source") -> list[SignatureCore]:
    path = tmp_path / f"{role}_mod.py"
    path.write_text(source, encoding="utf-8")
    adapter = default_language_registry().adapter_for_language("Python")
    assert adapter is not None
    analysis = adapter.extract_analysis(LanguageAnalysisContext(path, path.name, role, "Python"))
    return [item.core for item in signature_analyses_from_records(analysis.signatures)]


def test_a_block_inside_different_functions_is_found_with_its_lines(tmp_path: Path) -> None:
    cores = _cores(
        tmp_path,
        f"def load(job):\n{BLOCK}    return read(source, size)\n\n\n"
        f"def save(job, rows):\n    '''Save.'''\n{BLOCK}"
        "    write(source, rows)\n    return len(rows)\n",
    )

    (block,) = shared_blocks(cores)

    assert [(item.member.symbol, item.start_line, item.end_line) for item in block.occurrences] == [
        ("load", 2, 9),
        ("save", 15, 22),
    ]
    assert block.statement_count == 6  # noqa: PLR2004


@pytest.mark.parametrize(
    "source",
    [
        f"def load(job):\n{BLOCK}\n\ndef save(job):\n    '''Save.'''\n{BLOCK}",
        "def a(t):\n"
        + "    if 'x' in t:\n        r += 1\n" * 6
        + "\n\ndef b(t):\n"
        + "    if 'y' in t:\n        r += 2\n" * 6,
        f"def load(job):\n{BLOCK}    return 1\n\n\ndef save(job):\n    pass\n{BLOCK[:60]}\n",
    ],
    ids=["whole-function-clone", "one-repeated-statement", "too-short"],
)
def test_clones_patterns_and_short_runs_are_not_blocks(tmp_path: Path, source: str) -> None:
    assert shared_blocks(_cores(tmp_path, source)) == []


def test_test_code_and_compared_clones_are_left_out(tmp_path: Path) -> None:
    source_cores = _cores(tmp_path, f"def load(job):\n{BLOCK}    return 1\n")
    test_cores = _cores(tmp_path, f"def test_load(job):\n{BLOCK}    assert job\n", role="test")
    pair = _cores(
        tmp_path / "..", f"def a(job):\n{BLOCK}    return 1\n\n\ndef b(job):\n{BLOCK}    return 2\n"
    )

    assert shared_blocks([*source_cores, *test_cores]) == []
    assert shared_blocks(pair, related={frozenset(member_identity(core) for core in pair)}) == []
