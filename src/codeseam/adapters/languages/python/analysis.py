from __future__ import annotations

import ast
import io
import tokenize
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
    return parse_python_source(path.read_bytes())


def parse_python_source(data: bytes) -> PythonAnalysis:
    try:
        source = decode_python_source(data)
        tree = ast.parse(source)
    except SyntaxError as exc:
        return PythonAnalysis("", [], None, exc)
    return PythonAnalysis(source, source.splitlines(), tree)


def decode_python_source(data: bytes) -> str:
    """Decode with the file's coding cookie or BOM, as the interpreter would."""

    encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
    return data.decode(encoding)
