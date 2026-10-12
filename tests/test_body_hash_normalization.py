"""Body-hash identity must survive renaming but not changes in behaviour."""

from __future__ import annotations

from pathlib import Path

import pytest
from helpers import extract_source


def _body_hash(tmp_path: Path, language: str, source: str, name: str) -> str:
    (signature,) = extract_source(tmp_path / name, language, source).signatures
    assert signature.body_shape_hash
    return signature.body_shape_hash


@pytest.mark.parametrize(
    ("language", "left", "right"),
    [
        ("Python", "def f(a, b):\n    return a + b\n", "def f(a, b):\n    return a - b\n"),
        ("Python", "def f(a, b):\n    return a > b\n", "def f(a, b):\n    return a < b\n"),
        ("Python", "def f(x):\n    return read_json(x)\n", "def f(x):\n    return delete_all(x)\n"),
        (
            "Python",
            "def f(x):\n    return g(x, strict=True)\n",
            "def f(x):\n    return g(x, force=True)\n",
        ),
        (
            "Python",
            "def f(x):\n    y = x\n    z = x\n    return y\n",
            "def f(x):\n    y = x\n    z = x\n    return z\n",
        ),
        ("TypeScript", "function f(a, b) { return a + b; }", "function f(a, b) { return a - b; }"),
        ("TypeScript", "function f(a, b) { return a < b; }", "function f(a, b) { return a > b; }"),
        (
            "TypeScript",
            "function f(a, b) { return a && b; }",
            "function f(a, b) { return a || b; }",
        ),
        (
            "TypeScript",
            "function f(a) { return a === 1; }",
            "function f(a) { return a !== 1; }",
        ),
        (
            "TypeScript",
            "function f(a) { a += 1; return a; }",
            "function f(a) { a -= 1; return a; }",
        ),
        ("TypeScript", "function f(a) { return !a; }", "function f(a) { return -a; }"),
        (
            "TypeScript",
            "function f(o) { for (const k in o) { use(k); } }",
            "function f(o) { for (const k of o) { use(k); } }",
        ),
    ],
)
def test_body_hash_distinguishes_behavioural_changes(
    tmp_path: Path,
    language: str,
    left: str,
    right: str,
) -> None:
    assert _body_hash(tmp_path, language, left, "left") != _body_hash(
        tmp_path, language, right, "right"
    )


@pytest.mark.parametrize(
    ("language", "left", "right"),
    [
        (
            "Python",
            "def load(path):\n    raw = path.read_text()\n    return json.loads(raw)\n",
            "def fetch(source):\n    text = source.read_text()\n    return json.loads(text)\n",
        ),
        (
            "Python",
            "def f(rows):\n    return [clean(row) for row in rows]\n",
            "def g(items):\n    return [clean(item) for item in items]\n",
        ),
        (
            "Python",
            "def fact(n):\n    return 1 if n < 2 else n * fact(n - 1)\n",
            "def factorial(k):\n    return 1 if k < 2 else k * factorial(k - 1)\n",
        ),
        (
            "TypeScript",
            "function f(a, b) { const s = a + b; return s; }",
            "function g(x, y) { const t = x + y; return t; }",
        ),
    ],
)
def test_body_hash_survives_capture_safe_renaming(
    tmp_path: Path,
    language: str,
    left: str,
    right: str,
) -> None:
    assert _body_hash(tmp_path, language, left, "left") == _body_hash(
        tmp_path, language, right, "right"
    )
