from __future__ import annotations

from codeseam.analysis import OrderedTree
from codeseam.platform import Json


def tree_payload(tree: OrderedTree) -> Json:
    return {
        "label": tree.label,
        "children": [tree_payload(child) for child in tree.children],
    }


__all__ = ["tree_payload"]
