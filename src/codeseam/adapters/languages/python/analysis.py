from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

type PythonFunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


@dataclass
class PythonAnalysis:
    source: str
    lines: list[str]
    tree: ast.AST | None
    syntax_error: SyntaxError | None = None
    function_nodes: dict[tuple[str, int], PythonFunctionNode] = field(default_factory=dict)


def parse_python(path: Path) -> PythonAnalysis:
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return PythonAnalysis(source, source.splitlines(), None, exc)
    return PythonAnalysis(source, source.splitlines(), tree)
