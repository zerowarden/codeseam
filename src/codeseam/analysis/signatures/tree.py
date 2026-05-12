from __future__ import annotations

from dataclasses import dataclass
from functools import cache


@dataclass(frozen=True)
class OrderedTree:
    label: str
    children: tuple[OrderedTree, ...] = ()


@cache
def ordered_tree_size(tree: OrderedTree) -> int:
    return 1 + sum(ordered_tree_size(child) for child in tree.children)


__all__ = ["OrderedTree", "ordered_tree_size"]
