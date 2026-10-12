from __future__ import annotations

import ast
from collections.abc import Iterator

type ScopeNode = ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef


def dump_ast_shape(node: ast.AST) -> str:
    return ast.dump(node, annotate_fields=False, include_attributes=False)


def unparse_ast(node: ast.AST | None, default: str = "") -> str:
    return ast.unparse(node) if node is not None else default


def unparse_preview(node: ast.AST, limit: int) -> str:
    preview = ast.unparse(node)
    return preview if len(preview) <= limit else f"{preview[:limit]}..."


def named_lambda(node: ast.AST) -> ast.FunctionDef | None:
    """`name = lambda args: value` as the equivalent `def name(args): return value`.

    ECMAScript extracts `const name = (args) => value`; this keeps Python level.
    """

    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        target, value = node.targets[0], node.value
    elif isinstance(node, ast.AnnAssign) and node.value is not None:
        target, value = node.target, node.value
    else:
        return None
    if not (isinstance(target, ast.Name) and isinstance(value, ast.Lambda)):
        return None
    body = ast.copy_location(ast.Return(value=value.body), value.body)
    function = ast.FunctionDef(
        name=target.id,
        args=value.args,
        body=[body],
        decorator_list=[],
        returns=None,
        type_params=[],
    )
    ast.fix_missing_locations(ast.copy_location(function, node))
    return function


def iter_scoped_definitions(tree: ast.AST) -> Iterator[tuple[ScopeNode, tuple[str, ...]]]:
    """Classes and functions in source order with their enclosing scope names.

    Iterative, so deeply nested expressions cannot overflow the stack.
    """

    stack: list[tuple[ast.AST, tuple[str, ...]]] = [(tree, ())]
    while stack:
        node, scope = stack.pop()
        if node is not tree and isinstance(
            node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
        ):
            yield node, scope
            scope = (*scope, node.name)
        elif lambda_function := named_lambda(node):
            yield lambda_function, scope
        stack.extend((child, scope) for child in reversed(list(ast.iter_child_nodes(node))))
