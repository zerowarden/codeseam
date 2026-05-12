from __future__ import annotations

import ast
from typing import cast

from codeseam.analysis import (
    DuplicateBlockCandidate,
    IntraFunctionDuplicateBlock,
    duplicate_block_candidate,
    duplicate_blocks_from_candidates,
)

BODY_FIELD_NAMES = ("body", "orelse", "finalbody")
NESTED_SCOPE_TYPES = frozenset({ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef})


def python_intra_function_duplicate_blocks(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[IntraFunctionDuplicateBlock, ...]:
    return duplicate_blocks_from_candidates(_BlockCollector().collect(node.body))


class _BlockCollector:
    """Collect local duplicate candidates by walking statement bodies only."""

    def __init__(self) -> None:
        self._items: list[DuplicateBlockCandidate] = []

    def collect(self, body: list[ast.stmt]) -> list[DuplicateBlockCandidate]:
        self._visit_body(body)
        return self._items

    def _visit_body(self, body: list[ast.stmt]) -> None:
        for statement in body:
            if type(statement) is ast.If:
                self._add_block("if_body", statement.body)
                self._add_block("if_else", statement.orelse)
            elif type(statement) is ast.Try:
                self._add_block("try_else", statement.orelse)
                self._add_block("try_finally", statement.finalbody)
                for handler in statement.handlers:
                    self._add_block("except_handler", handler.body)
                    self._visit_body(handler.body)
            elif type(statement) in NESTED_SCOPE_TYPES:
                continue
            self._visit_statement_bodies(statement)

    def _visit_statement_bodies(self, statement: ast.stmt) -> None:
        for field_name in BODY_FIELD_NAMES:
            value = getattr(statement, field_name, None)
            if value:
                self._visit_body(cast(list[ast.stmt], value))
        if type(statement) is ast.Match:
            for case in statement.cases:
                self._visit_body(case.body)

    def _add_block(self, kind: str, body: list[ast.stmt]) -> None:
        if not body:
            return
        first = body[0]
        last = body[-1]
        start_line = int(getattr(first, "lineno", 0))
        end_line = int(getattr(last, "end_lineno", getattr(last, "lineno", 0)))
        candidate = duplicate_block_candidate(
            kind=kind,
            normalized_shape=ast.dump(
                ast.Module(body=body, type_ignores=[]),
                annotate_fields=True,
                include_attributes=False,
            ),
            statement_count=len(body),
            start_line=start_line,
            end_line=end_line,
        )
        if candidate is not None:
            self._items.append(candidate)


__all__ = ["python_intra_function_duplicate_blocks"]
