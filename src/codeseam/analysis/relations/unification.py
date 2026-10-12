from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from codeseam.analysis.signatures import OrderedTree, ordered_tree_size
from codeseam.platform import common_prefix_length, common_suffix_length

HOLE_PREFIX = "HOLE:"
OPERATOR_PREFIX = "op:"
ROLE_STATEMENT_SEQUENCE_DELTA = "statement_sequence_delta"
ARGUMENT_RE = re.compile(r"\bARG[0-9]+\b")


@dataclass(frozen=True)
class SequenceTemplateItem:
    kind: str
    token: str = ""
    id: str = ""
    role: str = ""
    roles: tuple[str, ...] = ()


@dataclass(frozen=True)
class SequenceSkeleton:
    template: tuple[SequenceTemplateItem, ...]
    hole_bindings: dict[str, dict[str, tuple[str, ...]]]
    stable_statement_count: int
    stable_node_ratio: float
    common_prefix_length: int
    common_suffix_length: int
    common_prefix_ratio: float
    hole_count: int
    max_hole_size: int
    hole_size_variance: str
    shared_param_flow_through_holes: bool


@dataclass(frozen=True)
class TreeSkeleton:
    template: OrderedTree
    hole_bindings: dict[str, dict[str, tuple[OrderedTree, ...]]]
    stable_node_count: int
    stable_node_ratio: float
    hole_count: int
    max_hole_size: int


def anti_unify_sequences(  # noqa: PLR0913
    left: list[str],
    right: list[str],
    *,
    left_keys: list[str] | None = None,
    right_keys: list[str] | None = None,
    left_id: str = "left",
    right_id: str = "right",
) -> SequenceSkeleton:
    """Align statements by key (content) and keep the tokens for the template."""

    left_keys = left_keys or left
    right_keys = right_keys or right
    matches = _lcs_matches(left_keys, right_keys)
    gaps = _gaps(matches, len(left), len(right))
    # Statements present in gaps on both sides moved rather than changed
    # (reordered guard clauses): they are stable, not holes.
    moved = Counter(left_keys[i] for gap, _ in gaps for i in gap) & Counter(
        right_keys[j] for _, gap in gaps for j in gap
    )
    left_budget, right_budget = moved.copy(), moved.copy()
    builder = _SequenceSkeletonBuilder(left_id, right_id)
    for (left_gap, right_gap), match in zip(gaps, [*matches, None], strict=True):
        left_moved, left_kept = _split_moved(left_gap, left_keys, left_budget)
        _, right_kept = _split_moved(right_gap, right_keys, right_budget)
        builder.template.extend(
            SequenceTemplateItem("STABLE_STATEMENT", token=left[index]) for index in left_moved
        )
        builder.append_hole([left[i] for i in left_kept], [right[j] for j in right_kept])
        if match is not None:
            builder.template.append(SequenceTemplateItem("STABLE_STATEMENT", token=left[match[0]]))
    stable_count = len(matches) + moved.total()
    max_count = max(len(left), len(right), 1)
    prefix = common_prefix_length(left_keys, right_keys)
    return SequenceSkeleton(
        template=tuple(builder.template),
        hole_bindings=builder.bindings,
        stable_statement_count=stable_count,
        stable_node_ratio=round(stable_count / max_count, 4),
        common_prefix_length=prefix,
        common_suffix_length=common_suffix_length(left_keys, right_keys, prefix),
        common_prefix_ratio=round(prefix / max_count, 4),
        hole_count=len(builder.holes),
        max_hole_size=_max_hole_size(builder.holes),
        hole_size_variance=_hole_size_variance(builder.holes),
        shared_param_flow_through_holes=_shared_param_flow(builder.holes),
    )


def _gaps(
    matches: list[tuple[int, int]], left_count: int, right_count: int
) -> list[tuple[list[int], list[int]]]:
    """Unmatched index runs before each match, plus the trailing run."""

    gaps: list[tuple[list[int], list[int]]] = []
    left_index = right_index = 0
    for match_left, match_right in [*matches, (left_count, right_count)]:
        gaps.append((list(range(left_index, match_left)), list(range(right_index, match_right))))
        left_index, right_index = match_left + 1, match_right + 1
    return gaps


def _split_moved(
    indexes: list[int], keys: list[str], budget: Counter[str]
) -> tuple[list[int], list[int]]:
    moved: list[int] = []
    kept: list[int] = []
    for index in indexes:
        if budget[keys[index]] > 0:
            budget[keys[index]] -= 1
            moved.append(index)
        else:
            kept.append(index)
    return moved, kept


def anti_unify_trees(
    left: OrderedTree,
    right: OrderedTree,
    *,
    left_id: str = "left",
    right_id: str = "right",
) -> TreeSkeleton:
    builder = _TreeSkeletonBuilder(left_id, right_id)
    template = builder.unify(left, right)
    max_size = max(ordered_tree_size(left), ordered_tree_size(right), 1)
    return TreeSkeleton(
        template=template,
        hole_bindings=builder.bindings,
        stable_node_count=builder.stable_node_count,
        stable_node_ratio=round(builder.stable_node_count / max_size, 4),
        hole_count=builder.hole_count,
        max_hole_size=builder.max_hole_size,
    )


def operator_changed(left: OrderedTree, right: OrderedTree) -> bool:
    """Whether aligned code differs by an operator: substituted, added or removed.

    A hole counts when its two sides are equal once operator leaves (`op:`) are
    dropped and unary-operator wrappers unwrapped (`a + b`/`a - b`, `not x`/`x`).
    Inserted statements that merely contain operators do not count.
    """

    skeleton = anti_unify_trees(left, right)
    left_holes, right_holes = skeleton.hole_bindings["left"], skeleton.hole_bindings["right"]
    return any(
        _operator_labels(left_holes[hole]) != _operator_labels(right_holes[hole])
        and _without_operators(left_holes[hole]) == _without_operators(right_holes[hole])
        for hole in left_holes
    )


def _operator_labels(trees: tuple[OrderedTree, ...]) -> list[str]:
    labels: list[str] = []
    stack = list(trees)
    while stack:
        node = stack.pop()
        if node.label.startswith(OPERATOR_PREFIX):
            labels.append(node.label)
        stack.extend(node.children)
    return sorted(labels)


def _without_operators(trees: tuple[OrderedTree, ...]) -> tuple[OrderedTree, ...]:
    stripped: list[OrderedTree] = []
    for tree in trees:
        if tree.label.startswith(OPERATOR_PREFIX):
            continue
        has_operator = any(child.label.startswith(OPERATOR_PREFIX) for child in tree.children)
        children = _without_operators(tree.children)
        if has_operator and len(children) == 1:  # a unary-operator wrapper such as `not x`
            stripped.append(children[0])
        else:
            stripped.append(OrderedTree(tree.label, children))
    return tuple(stripped)


class _SequenceSkeletonBuilder:
    def __init__(self, left_id: str, right_id: str) -> None:
        self.left_id = left_id
        self.right_id = right_id
        self.template: list[SequenceTemplateItem] = []
        self.bindings: dict[str, dict[str, tuple[str, ...]]] = {left_id: {}, right_id: {}}
        self.holes: list[tuple[list[str], list[str]]] = []

    def append_hole(self, left_items: list[str], right_items: list[str]) -> None:
        if not left_items and not right_items:
            return
        hole_id = f"H{len(self.holes)}"
        self.template.append(
            SequenceTemplateItem(
                "HOLE",
                id=hole_id,
                role=ROLE_STATEMENT_SEQUENCE_DELTA,
                roles=tuple(_hole_roles(left_items, right_items)),
            )
        )
        self.bindings[self.left_id][hole_id] = tuple(left_items)
        self.bindings[self.right_id][hole_id] = tuple(right_items)
        self.holes.append((left_items, right_items))


class _TreeSkeletonBuilder:
    def __init__(self, left_id: str, right_id: str) -> None:
        self.left_id = left_id
        self.right_id = right_id
        self.bindings: dict[str, dict[str, tuple[OrderedTree, ...]]] = {
            left_id: {},
            right_id: {},
        }
        self.stable_node_count = 0
        self.hole_count = 0
        self.max_hole_size = 0

    def unify(self, left: OrderedTree, right: OrderedTree) -> OrderedTree:
        if left.label != right.label:
            return self._hole([left], [right])
        self.stable_node_count += 1
        return OrderedTree(
            left.label,
            tuple(self._unify_children(left.children, right.children)),
        )

    def _unify_children(
        self,
        left_children: tuple[OrderedTree, ...],
        right_children: tuple[OrderedTree, ...],
    ) -> list[OrderedTree]:
        children: list[OrderedTree] = []
        left_index = 0
        right_index = 0
        for match_left, match_right in _lcs_matches(
            [child.label for child in left_children],
            [child.label for child in right_children],
        ):
            if left_index < match_left or right_index < match_right:
                children.append(
                    self._hole(
                        list(left_children[left_index:match_left]),
                        list(right_children[right_index:match_right]),
                    )
                )
            children.append(self.unify(left_children[match_left], right_children[match_right]))
            left_index = match_left + 1
            right_index = match_right + 1
        if left_index < len(left_children) or right_index < len(right_children):
            children.append(
                self._hole(
                    list(left_children[left_index:]),
                    list(right_children[right_index:]),
                )
            )
        return children

    def _hole(self, left_items: list[OrderedTree], right_items: list[OrderedTree]) -> OrderedTree:
        hole_id = f"H{self.hole_count}"
        left_size = sum(ordered_tree_size(item) for item in left_items)
        right_size = sum(ordered_tree_size(item) for item in right_items)
        self.hole_count += 1
        self.max_hole_size = max(self.max_hole_size, left_size, right_size)
        self.bindings[self.left_id][hole_id] = tuple(left_items)
        self.bindings[self.right_id][hole_id] = tuple(right_items)
        return OrderedTree(f"{HOLE_PREFIX}{hole_id}")


def _lcs_matches(left: list[str], right: list[str]) -> list[tuple[int, int]]:
    rows = len(left) + 1
    cols = len(right) + 1
    table = [[0] * cols for _ in range(rows)]
    for row in range(len(left) - 1, -1, -1):
        for col in range(len(right) - 1, -1, -1):
            if left[row] == right[col]:
                table[row][col] = table[row + 1][col + 1] + 1
            else:
                table[row][col] = max(table[row + 1][col], table[row][col + 1])
    row = 0
    col = 0
    matches: list[tuple[int, int]] = []
    while row < len(left) and col < len(right):
        if left[row] == right[col]:
            matches.append((row, col))
            row += 1
            col += 1
        elif table[row + 1][col] >= table[row][col + 1]:
            row += 1
        else:
            col += 1
    return matches


def _hole_roles(left_items: list[str], right_items: list[str]) -> list[str]:
    text = " ".join([*left_items, *right_items]).lower()
    roles = []
    if "call" in text:
        roles.append("call_delta")
    if any(token in text for token in ("const", "literal", '"', "'", " true", " false", " none")):
        roles.append("literal_delta")
    if "receiver" in text or "." in text or "attr" in text:
        roles.append("receiver_delta")
    if any(token in text for token in ("if", "for", "while", "with", "branch", "match", "switch")):
        roles.append("branch_delta")
    if any(token in text for token in ("raise", "throw", "except", "catch", "error")):
        roles.append("error_delta")
    if "return" in text:
        roles.append("return_delta")
    return roles or [ROLE_STATEMENT_SEQUENCE_DELTA]


def _max_hole_size(holes: list[tuple[list[str], list[str]]]) -> int:
    return max((max(len(left), len(right)) for left, right in holes), default=0)


def _hole_size_variance(holes: list[tuple[list[str], list[str]]]) -> str:
    if not holes:
        return "none"
    largest_delta = max(abs(len(left) - len(right)) for left, right in holes)
    return "low" if largest_delta <= 1 else "high"


def _shared_param_flow(holes: list[tuple[list[str], list[str]]]) -> bool:
    return any(
        _arg_tokens(left_items) & _arg_tokens(right_items) for left_items, right_items in holes
    )


def _arg_tokens(items: list[str]) -> set[str]:
    return {match.group(0) for item in items for match in ARGUMENT_RE.finditer(item)}


__all__ = [
    "SequenceSkeleton",
    "SequenceTemplateItem",
    "TreeSkeleton",
    "anti_unify_sequences",
    "anti_unify_trees",
    "operator_changed",
]
