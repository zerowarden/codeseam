from __future__ import annotations

from codeseam.analysis.signatures import OrderedTree


def ordered_tree_edit_distance(left: OrderedTree, right: OrderedTree) -> int:
    """Top-down ordered tree edit distance (Selkow).

    A node may be relabelled; inserting or deleting a child costs the size of its
    subtree, and children are aligned in order. Only nodes at the same depth are
    ever aligned, so nodes are flattened to post-order indexes and the table is
    filled bottom-up for same-depth pairs only, without recursion or hashing
    whole subtrees.
    """

    left_labels, left_children, left_sizes, left_depths = _flatten(left)
    right_labels, right_children, right_sizes, right_depths = _flatten(right)
    right_by_depth: dict[int, list[int]] = {}
    for j, depth in enumerate(right_depths):
        right_by_depth.setdefault(depth, []).append(j)
    distance: list[dict[int, int]] = [{} for _ in left_labels]
    for i, label in enumerate(left_labels):
        children = left_children[i]
        row = distance[i]
        for j in right_by_depth.get(left_depths[i], ()):
            others = right_children[j]
            previous = [0]
            for child in others:
                previous.append(previous[-1] + right_sizes[child])
            for child in children:
                current = [previous[0] + left_sizes[child]]
                child_row = distance[child]
                for k, other_child in enumerate(others):
                    current.append(
                        min(
                            previous[k + 1] + left_sizes[child],
                            current[k] + right_sizes[other_child],
                            previous[k] + child_row[other_child],
                        )
                    )
                previous = current
            row[j] = (label != right_labels[j]) + previous[-1]
    return distance[-1][len(right_labels) - 1]


def body_tree_edit_distance(left: OrderedTree, right: OrderedTree) -> int:
    """Edit distance between function bodies that lets identical statements move.

    Top-level statements with identical subtrees pair up wherever they sit
    (reordered guard clauses are the same body); the rest are aligned in order.
    """

    remaining = list(right.children)
    unmatched: list[OrderedTree] = []
    for statement in left.children:
        if statement in remaining:
            remaining.remove(statement)
        else:
            unmatched.append(statement)
    return (left.label != right.label) + ordered_tree_edit_distance(
        OrderedTree("", tuple(unmatched)), OrderedTree("", tuple(remaining))
    )


def tree_shape(tree: OrderedTree) -> tuple[int, ...]:
    """Pre-order child counts: equal for trees that differ only in labels."""

    shape: list[int] = []
    stack = [tree]
    while stack:
        node = stack.pop()
        shape.append(len(node.children))
        stack.extend(reversed(node.children))
    return tuple(shape)


def _flatten(tree: OrderedTree) -> tuple[list[str], list[list[int]], list[int], list[int]]:
    """Post-order labels, child indexes, subtree sizes and depths; the root comes last."""

    labels: list[str] = []
    children: list[list[int]] = []
    sizes: list[int] = []
    depths: list[int] = []
    # (node, depth, the parent's child-index list, this node's own list once expanded)
    stack: list[tuple[OrderedTree, int, list[int] | None, list[int] | None]] = [
        (tree, 0, None, None)
    ]
    while stack:
        node, depth, siblings, own = stack.pop()
        if own is None:
            own = []
            stack.append((node, depth, siblings, own))
            stack.extend((child, depth + 1, own, None) for child in reversed(node.children))
            continue
        if siblings is not None:
            siblings.append(len(labels))
        labels.append(node.label)
        children.append(own)
        sizes.append(1 + sum(sizes[child] for child in own))
        depths.append(depth)
    return labels, children, sizes, depths


__all__ = ["body_tree_edit_distance", "ordered_tree_edit_distance", "tree_shape"]
