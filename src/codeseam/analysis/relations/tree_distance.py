from __future__ import annotations

from functools import cache

from codeseam.analysis.signatures import OrderedTree, ordered_tree_size


def ordered_tree_edit_distance(left: OrderedTree, right: OrderedTree) -> int:
    @cache
    def distance(left_tree: OrderedTree, right_tree: OrderedTree) -> int:
        relabel_cost = 0 if left_tree.label == right_tree.label else 1
        return relabel_cost + forest_distance(left_tree.children, right_tree.children)

    @cache
    def forest_distance(
        left_forest: tuple[OrderedTree, ...],
        right_forest: tuple[OrderedTree, ...],
    ) -> int:
        rows = len(left_forest) + 1
        cols = len(right_forest) + 1
        table = [[0] * cols for _ in range(rows)]
        for row in range(1, rows):
            table[row][0] = table[row - 1][0] + ordered_tree_size(left_forest[row - 1])
        for col in range(1, cols):
            table[0][col] = table[0][col - 1] + ordered_tree_size(right_forest[col - 1])
        for row in range(1, rows):
            for col in range(1, cols):
                table[row][col] = min(
                    table[row - 1][col] + ordered_tree_size(left_forest[row - 1]),
                    table[row][col - 1] + ordered_tree_size(right_forest[col - 1]),
                    table[row - 1][col - 1] + distance(left_forest[row - 1], right_forest[col - 1]),
                )
        return table[-1][-1]

    return distance(left, right)


__all__ = ["ordered_tree_edit_distance"]
