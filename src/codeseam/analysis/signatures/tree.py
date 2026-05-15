from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OrderedTree:
    label: str
    children: tuple[OrderedTree, ...] = ()


def ordered_tree_size(tree: OrderedTree) -> int:
    return 1 + sum(ordered_tree_size(child) for child in tree.children)


__all__ = ["OrderedTree", "ordered_tree_size"]
