from __future__ import annotations

import ast


def dump_ast_shape(node: ast.AST) -> str:
    return ast.dump(node, annotate_fields=False, include_attributes=False)


def unparse_ast(node: ast.AST | None, default: str = "") -> str:
    return ast.unparse(node) if node is not None else default


def unparse_preview(node: ast.AST, limit: int) -> str:
    preview = ast.unparse(node)
    return preview if len(preview) <= limit else f"{preview[:limit]}..."


class ClassStackVisitor[T](ast.NodeVisitor):
    stack: list[str]
    records: list[T]

    def collect(self, tree: ast.AST) -> list[T]:
        self.visit(tree)
        return self.records

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()
