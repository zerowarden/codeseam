from __future__ import annotations


def lcs_length(left: list[str], right: list[str]) -> int:
    previous = [0] * (len(right) + 1)
    for item in left:
        current = [0]
        for index, other in enumerate(right, 1):
            if item == other:
                current.append(previous[index - 1] + 1)
            else:
                current.append(max(previous[index], current[-1]))
        previous = current
    return previous[-1]


def common_prefix_length(left: list[str], right: list[str]) -> int:
    count = 0
    for left_item, right_item in zip(left, right, strict=False):
        if left_item != right_item:
            break
        count += 1
    return count


def common_suffix_length(left: list[str], right: list[str], prefix: int = 0) -> int:
    count = 0
    left_tail = len(left) - prefix
    right_tail = len(right) - prefix
    while count < left_tail and count < right_tail:
        if left[-count - 1] != right[-count - 1]:
            break
        count += 1
    return count
