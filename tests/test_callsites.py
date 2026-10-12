"""Factory-use evidence follows lexical scope and the parse tree, not text."""

from __future__ import annotations

from pathlib import Path

import pytest
from helpers import extract_source

from codeseam.analysis import EvidenceKind

PY_FACTORY = "from typing import Callable\n\ndef make() -> Callable:\n    return print\n\n"
TS_FACTORY = "function make(): () => void { return () => {}; }\n"


def _kinds(tmp_path: Path, language: str, source: str) -> set[str]:
    factory_source = PY_FACTORY if language == "Python" else TS_FACTORY
    analysis = extract_source(tmp_path, language, factory_source + source)
    (factory,) = [record for record in analysis.signatures if record.symbol == "make"]
    return {pattern.kind for pattern in factory.callsite_patterns}


@pytest.mark.parametrize(
    ("language", "source", "expected"),
    [
        (
            "Python",
            "def run():\n    h = make()\n    h()\n    h()\n",
            {EvidenceKind.CALLSITE_STORED_REUSE},
        ),
        (
            "Python",
            "def run():\n    h = make()\n    h()\n    h = len\n    h()\n",
            set(),
        ),
        (
            "Python",
            "def run():\n    h = make()\n    h()\n\ndef other(h):\n    h()\n",
            set(),
        ),
        (
            "Python",
            "def run(obj):\n    h = make()\n    obj.h()\n    obj.h()\n",
            set(),
        ),
        ("Python", "def run():\n    make()()\n", {EvidenceKind.CALLSITE_IMMEDIATE}),
        ("Python", "def run(xs):\n    map(make(), xs)\n", {EvidenceKind.CALLSITE_PIPELINE}),
        (
            "Python",
            "def run(app):\n    app.add_handler(make())\n",
            {EvidenceKind.CALLSITE_REGISTERED},
        ),
        ("Python", "def run():\n    convert(make())\n", set()),
        ("Python", "def run(k):\n    _cache[k] = make()\n", {EvidenceKind.CALLSITE_CACHED}),
        ("Python", "def run(make):\n    make()()\n", set()),
        (
            "TypeScript",
            "function run() { const h = make(); h(); h(); }",
            {EvidenceKind.CALLSITE_STORED_REUSE},
        ),
        ("TypeScript", "function run() { const h = make(); h(); }\nfunction o(h) { h(); }", set()),
        (
            "TypeScript",
            "function run() {\n  make(\n  )(\n  );\n}",
            {EvidenceKind.CALLSITE_IMMEDIATE},
        ),
        ("TypeScript", "function run() {\n  // make()()\n  const s = 'make()()';\n}", set()),
        ("TypeScript", "function run(xs) { xs.map(make()); }", {EvidenceKind.CALLSITE_PIPELINE}),
        (
            "TypeScript",
            "function run(el) { el.addEventListener('x', make()); }",
            {EvidenceKind.CALLSITE_REGISTERED},
        ),
        ("TypeScript", "function run() { convert(make()); }", set()),
        ("TypeScript", "function run(k) { cache.set(k, make()); }", {EvidenceKind.CALLSITE_CACHED}),
    ],
    ids=[
        "py-stored-reuse",
        "py-reassigned",
        "py-other-scope",
        "py-attribute-not-variable",
        "py-immediate",
        "py-pipeline",
        "py-registered",
        "py-on-is-not-a-substring",
        "py-cached",
        "py-shadowed-factory",
        "ts-stored-reuse",
        "ts-other-scope",
        "ts-multiline",
        "ts-comments-and-strings",
        "ts-pipeline",
        "ts-registered",
        "ts-on-is-not-a-substring",
        "ts-cached",
    ],
)
def test_callsite_evidence_follows_scope_and_syntax(
    tmp_path: Path, language: str, source: str, expected: set[str]
) -> None:
    assert _kinds(tmp_path, language, source) == expected
