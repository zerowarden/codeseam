from __future__ import annotations

import re

from tree_sitter import Node

from codeseam.adapters.languages.ecmascript.runtime import node_text
from codeseam.adapters.languages.ecmascript.syntax_kinds import (
    CONTROL_BLOCK_PARENTS,
    CONTROL_CONTAINER_TYPES,
    IGNORED_STATEMENT_TYPES,
    NESTED_SCOPE_TYPES,
)
from codeseam.analysis import (
    DuplicateBlockCandidate,
    IntraFunctionDuplicateBlock,
    ParamIR,
    duplicate_block_bounds_ok,
    duplicate_block_candidate,
    duplicate_blocks_from_candidates,
)

WHITESPACE_RE = re.compile(r"\s+")


def ecmascript_intra_function_duplicate_blocks(
    source: bytes,
    body_node: Node | None,
    params: tuple[ParamIR, ...],
) -> tuple[IntraFunctionDuplicateBlock, ...]:
    """Collect repeated local branch/handler blocks from JS/TS syntax.

    Tree-sitter owns the syntax walk here, but grouping and scoring stay in the
    shared signature/assessment layers. Nested functions are skipped so an
    outer function is not credited for duplicate blocks owned by another
    callable boundary.
    """

    if body_node is None:
        return ()
    del params
    return duplicate_blocks_from_candidates(_block_candidates(source, body_node))


def _block_candidates(
    source: bytes,
    body_node: Node,
) -> tuple[DuplicateBlockCandidate, ...]:
    items: list[DuplicateBlockCandidate] = []
    _visit_statement_block(source, body_node, items)
    return tuple(items)


def _visit_statement_block(
    source: bytes,
    block: Node,
    items: list[DuplicateBlockCandidate],
) -> None:
    for statement in block.named_children:
        if statement.type in IGNORED_STATEMENT_TYPES | NESTED_SCOPE_TYPES:
            continue
        _visit_statement(source, statement, items)


def _visit_statement(
    source: bytes,
    statement: Node,
    items: list[DuplicateBlockCandidate],
) -> None:
    for child in statement.named_children:
        if child.type in NESTED_SCOPE_TYPES:
            continue
        if child.type == "statement_block":
            if _candidate_block(child):
                if candidate := _block_candidate(source, child):
                    items.append(candidate)
            _visit_statement_block(source, child, items)
        elif child.type in CONTROL_CONTAINER_TYPES:
            _visit_statement(source, child, items)


def _candidate_block(block: Node) -> bool:
    return block.parent is not None and block.parent.type in CONTROL_BLOCK_PARENTS


def _block_candidate(
    source: bytes,
    block: Node,
) -> DuplicateBlockCandidate | None:
    statement_count = _statement_count(block)
    start_line = block.start_point[0] + 1
    end_line = block.end_point[0] + 1
    if not duplicate_block_bounds_ok(
        statement_count=statement_count,
        start_line=start_line,
        end_line=end_line,
    ):
        return None
    return duplicate_block_candidate(
        kind=_block_kind(block),
        normalized_shape=_normalized_block_text(source, block),
        statement_count=statement_count,
        start_line=start_line,
        end_line=end_line,
    )


def _statement_count(node: Node) -> int:
    return sum(1 for child in node.named_children if child.type not in IGNORED_STATEMENT_TYPES)


def _block_kind(node: Node) -> str:
    return node.parent.type if node.parent is not None else node.type


def _normalized_block_text(source: bytes, node: Node) -> str:
    return WHITESPACE_RE.sub(" ", node_text(source, node) or "").strip()


__all__ = ["ecmascript_intra_function_duplicate_blocks"]
