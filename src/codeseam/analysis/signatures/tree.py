from __future__ import annotations

from dataclasses import dataclass

# Deeper body trees are not built: tree consumers (equality, anti-unification,
# the cache codec) recurse once per level, and pairs without trees use proxies.
MAX_TREE_DEPTH = 150


@dataclass(frozen=True, slots=True)
class OrderedTree:
    label: str
    children: tuple[OrderedTree, ...] = ()


def ordered_tree_size(tree: OrderedTree) -> int:
    size = 0
    stack = [tree]
    while stack:
        node = stack.pop()
        size += 1
        stack.extend(node.children)
    return size


__all__ = ["MAX_TREE_DEPTH", "OrderedTree", "ordered_tree_size"]
