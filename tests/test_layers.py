"""Packages import only from lower layers (docs/architecture.md#layers)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).parents[1] / "src" / "codeseam"
PACKAGE_LAYERS = {
    "platform": 0,
    "version": 0,
    "caveat_msg": 0,
    "semantics": 1,
    "analysis": 2,
    "cache": 3,
    "config": 3,
    "adapters.languages": 4,
    "adapters.repository": 5,
    "output": 5,
    "pipeline": 6,
    "profiling": 7,
    "cli": 8,
}
ANALYSIS_LAYERS = {
    "semantic_roles": 0,
    "signatures": 0,
    "repository": 0,
    "inventory": 1,
    "relations": 1,
    "clusters": 2,
    "findings": 3,
    "assessment": 4,
}


def _unit(parts: tuple[str, ...], layers: dict[str, int]) -> str | None:
    for size in (2, 1):
        name = ".".join(parts[:size]).removesuffix(".py")
        if name in layers:
            return name
    return None


def _imports(root: Path, prefix: str, layers: dict[str, int]) -> list[tuple[str, str, str]]:
    found = []
    for path in sorted(root.rglob("*.py")):
        source = _unit(path.relative_to(root).parts, layers)
        if source is None:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            module = node.module if isinstance(node, ast.ImportFrom) else None
            if module and module.startswith(prefix):
                target = _unit(tuple(module.removeprefix(prefix).split(".")), layers)
                if target is not None and target != source:
                    found.append((path.relative_to(SRC).as_posix(), source, target))
    return found


@pytest.mark.parametrize(
    ("root", "prefix", "layers"),
    [
        (SRC, "codeseam.", PACKAGE_LAYERS),
        (SRC / "analysis", "codeseam.analysis.", ANALYSIS_LAYERS),
    ],
    ids=["packages", "analysis"],
)
def test_imports_point_down_the_layers(root: Path, prefix: str, layers: dict[str, int]) -> None:
    upward = [
        f"{path}: {source} -> {target}"
        for path, source, target in _imports(root, prefix, layers)
        if layers[target] >= layers[source]
    ]

    assert upward == []
