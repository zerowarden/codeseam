"""One unreadable or pathological file must be reported, never abort the run."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from helpers import file_record, run_cli

from codeseam.adapters.languages import default_language_registry
from codeseam.adapters.languages.extraction import (
    FileAnalysisResult,
    analyze_language_file,
    language_context,
)
from codeseam.adapters.languages.python.signature_features import body_tree
from codeseam.analysis import ExtractionConfidence, build_clusters
from codeseam.cache import AnalysisCacheContext, LanguageRunCache, persistent_cache
from codeseam.caveat_msg import PARSE_ERROR_CAVEAT
from codeseam.platform import sha256_bytes

DEEP_SUM = b"def deep(x):\n    return " + b" + ".join([b"x"] * 3000) + b"\n"
DEEP_TS = b"function deep(x) { return " + b"(" * 3000 + b"x" + b")" * 3000 + b"; }\n"


def _analyze(
    tmp_path: Path,
    name: str,
    data: bytes,
    language: str = "Python",
) -> FileAnalysisResult:
    (tmp_path / name).write_bytes(data)
    record = file_record(name, language=language)
    return analyze_language_file(
        language_context(tmp_path, name, record),
        record,
        default_language_registry(),
        None,
    )


@pytest.mark.parametrize(
    ("data", "symbol"),
    [
        (b'# -*- coding: latin-1 -*-\nNAME = "caf\xe9"\ndef latin(x):\n    return x\n', "latin"),
        (b"\xef\xbb\xbfdef bom(x):\n    return x\n", "bom"),
    ],
)
def test_python_source_is_decoded_like_the_interpreter(
    tmp_path: Path,
    data: bytes,
    symbol: str,
) -> None:
    result = _analyze(tmp_path, "mod.py", data)

    assert [signature.core.symbol for signature in result.signatures] == [symbol]
    assert result.diagnostics == ()


@pytest.mark.parametrize(
    ("name", "data", "language", "diagnostic"),
    [
        ("syntax.py", b"def broken(:\n    pass\n", "Python", "python_parse_error: "),
        ("invalid.py", b'def bad(x):\n    return "\xff"\n', "Python", "extraction_failed: Unicode"),
    ],
)
def test_unparseable_files_yield_diagnostics_and_no_placeholder_records(
    tmp_path: Path,
    name: str,
    data: bytes,
    language: str,
    diagnostic: str,
) -> None:
    result = _analyze(tmp_path, name, data, language)

    assert result.functions == ()
    assert result.signatures == ()
    assert len(result.diagnostics) == 1
    assert result.diagnostics[0].startswith(diagnostic)


@pytest.mark.parametrize(
    ("name", "data", "language"),
    [("deep.py", DEEP_SUM, "Python"), ("deep.ts", DEEP_TS, "TypeScript")],
)
def test_deeply_nested_files_are_analysed(
    tmp_path: Path, name: str, data: bytes, language: str
) -> None:
    result = _analyze(tmp_path, name, data, language)

    assert [signature.core.symbol for signature in result.signatures] == ["deep"]
    assert result.signatures[0].core.body_shape_hash
    assert result.diagnostics == ()


def test_body_trees_past_the_depth_limit_are_skipped() -> None:
    (node,) = ast.parse(DEEP_SUM.decode()).body
    assert isinstance(node, ast.FunctionDef)

    assert body_tree(node) is None


@pytest.mark.integration
def test_analysis_completes_and_reports_failed_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "ok.py").write_text("def ok(y):\n    return y\n", encoding="utf-8")
    (tmp_path / "invalid.py").write_bytes(b'def bad(x):\n    return "\xff"\n')

    for _ in range(2):  # the second run must not hide the failure behind a cache hit
        run_cli(tmp_path, monkeypatch, ["analyze", "--no-progress"])
        assert "(0 skipped, 1 with errors)" in capsys.readouterr().out


BROKEN_TS_PAIR = (
    b"function left(x) { const y = x + ; return y; }\n"
    b"function right(x) { const y = x + ; return y; }\n"
)


def test_recovered_typescript_parse_is_low_confidence_and_reported(tmp_path: Path) -> None:
    result = _analyze(tmp_path, "broken.ts", BROKEN_TS_PAIR, "TypeScript")

    assert {function.extraction_confidence for function in result.functions} == {"low"}
    assert all(PARSE_ERROR_CAVEAT in sig.output.caveats for sig in result.signatures)
    assert result.diagnostics[0].startswith("tree_sitter_parse_error: 2 function(s)")
    (cluster,) = build_clusters(result.signatures)
    assert cluster.min_extraction_confidence is ExtractionConfidence.LOW


def test_typescript_file_without_recoverable_functions_is_reported(tmp_path: Path) -> None:
    result = _analyze(tmp_path, "garbage.ts", b"}}} ((( export = = ;\n", "TypeScript")

    assert result.functions == ()
    assert result.diagnostics == ("tree_sitter_parse_error: no functions recovered",)


@pytest.mark.parametrize(
    ("name", "language", "old", "new"),
    [
        ("mod.py", "Python", b"def old():\n    return 1\n", b"def new():\n    return 2\n"),
        ("mod.ts", "TypeScript", b"function old() { return 1; }\n", b"function nu() {}\n"),
    ],
)
def test_files_edited_after_the_scan_are_reported_and_never_cached_under_the_old_hash(
    tmp_path: Path, name: str, language: str, old: bytes, new: bytes
) -> None:
    record = file_record(name, language=language, content_hash=sha256_bytes(old))
    registry = default_language_registry()
    cache = persistent_cache(tmp_path / ".cache", enabled=True)

    def analyze() -> FileAnalysisResult:
        caches = AnalysisCacheContext(
            persistent=cache,
            file_analysis_enabled=True,
            relation_pair_enabled=False,
            language=LanguageRunCache(),
        )
        return analyze_language_file(
            language_context(tmp_path, name, record), record, registry, caches
        )

    try:
        (tmp_path / name).write_bytes(new)
        edited = analyze()
        (tmp_path / name).write_bytes(old)
        restored = analyze()
    finally:
        cache.close()

    assert edited.signatures == ()
    assert edited.diagnostics[0].startswith("source_changed:")
    assert [signature.core.symbol for signature in restored.signatures] == ["old"]
