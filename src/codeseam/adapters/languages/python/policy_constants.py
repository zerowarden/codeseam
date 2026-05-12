from __future__ import annotations

import ast
from typing import cast

from codeseam.adapters.languages.python.analysis import PythonAnalysis
from codeseam.adapters.languages.python.ast_utils import dump_ast_shape, unparse_preview
from codeseam.analysis import PolicyConstant
from codeseam.platform import normalize_identifier, sha256_text

MIN_STRUCTURED_LITERAL_ITEMS = 2
PREVIEW_LIMIT = 120


def extract_policy_constants(
    *,
    language: str,
    relative_path: str,
    role: str,
    analysis: PythonAnalysis,
) -> list[PolicyConstant]:
    if analysis.syntax_error or type(analysis.tree) is not ast.Module:
        return []
    constants: list[PolicyConstant] = []
    for node in analysis.tree.body:
        name, value = _constant_assignment(node)
        if not name or value is None or not _is_policy_constant_name(name):
            continue
        if not _structured_policy_literal_items(value):
            continue
        literal_shape = dump_ast_shape(value)
        constants.append(
            PolicyConstant(
                language=language,
                file=relative_path,
                symbol=name,
                normalized_symbol=normalize_identifier(name),
                start_line=int(getattr(node, "lineno", 1)),
                end_line=int(getattr(node, "end_lineno", getattr(node, "lineno", 1))),
                role=role,
                literal_kind=type(value).__name__,
                literal_shape_hash=sha256_text(literal_shape),
                literal_preview=unparse_preview(value, PREVIEW_LIMIT),
            )
        )
    return constants


def _constant_assignment(node: ast.stmt) -> tuple[str | None, ast.AST | None]:
    node_type = type(node)
    if node_type is ast.Assign:
        assignment = cast(ast.Assign, node)
        if len(assignment.targets) == 1:
            target = assignment.targets[0]
            if type(target) is ast.Name:
                return target.id, assignment.value
    if node_type is ast.AnnAssign:
        annotated = cast(ast.AnnAssign, node)
        if type(annotated.target) is ast.Name:
            return annotated.target.id, annotated.value
    return None, None


def _is_policy_constant_name(name: str) -> bool:
    return name.isupper() and "_" in name


def _structured_policy_literal_items(value: ast.AST) -> tuple[ast.AST, ...]:
    value_type = type(value)
    if value_type is ast.Dict:
        literal = cast(ast.Dict, value)
        items = tuple(item for item in [*literal.keys, *literal.values] if item is not None)
    elif value_type is ast.List:
        items = tuple(cast(ast.List, value).elts)
    elif value_type is ast.Tuple:
        items = tuple(cast(ast.Tuple, value).elts)
    elif value_type is ast.Set:
        items = tuple(cast(ast.Set, value).elts)
    else:
        return ()
    if len(items) < MIN_STRUCTURED_LITERAL_ITEMS or not all(
        _is_simple_literal(item) for item in items
    ):
        return ()
    return items


def _is_simple_literal(node: ast.AST) -> bool:
    node_type = type(node)
    if node_type is ast.Constant:
        return type(cast(ast.Constant, node).value) in {str, int, float, bool, type(None)}
    if node_type is ast.UnaryOp:
        unary = cast(ast.UnaryOp, node)
        if type(unary.op) is not ast.USub:
            return False
        return type(unary.operand) is ast.Constant and isinstance(
            unary.operand.value,
            int | float,
        )
    return False
