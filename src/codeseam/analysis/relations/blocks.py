"""Partial clones: one run of statements shared by otherwise different functions.

Whole-function comparison misses a large block copied into two functions that
differ elsewhere, because the functions as a whole are not similar enough.
This stage indexes windows of consecutive top-level statement keys (Type-2:
names and literal values abstracted), pairs functions that share a rare
window, and extends each match to the longest common run.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Collection, Iterator, Sequence
from dataclasses import dataclass
from itertools import combinations

from codeseam.analysis.relations.policy import BLOCK_POLICY, BlockPolicy
from codeseam.analysis.signatures import SignatureCore, StatementKind

TEST_ROLES = frozenset({"test", "fixture"})
type _Run = tuple[
    int, int, int, int, int
]  # left member, left start, right member, right start, length


@dataclass(frozen=True, slots=True)
class BlockOccurrence:
    member: SignatureCore
    start: int  # index of the first statement
    length: int

    @property
    def start_line(self) -> int:
        return self.member.statement_spans[self.start][0]

    @property
    def end_line(self) -> int:
        return self.member.statement_spans[self.start + self.length - 1][1]

    @property
    def line_count(self) -> int:
        return self.end_line - self.start_line + 1


@dataclass(frozen=True, slots=True)
class SharedBlock:
    """Every run of statements one set of functions shares: one finding per set."""

    occurrences: tuple[BlockOccurrence, ...]

    @property
    def members(self) -> tuple[SignatureCore, ...]:
        return tuple(dict.fromkeys(item.member for item in self.occurrences))

    @property
    def statement_count(self) -> int:
        return max(item.length for item in self.occurrences)

    @property
    def fingerprint(self) -> str:
        parts = (
            f"{item.member.file}:{item.member.symbol}:{item.length}" for item in self.occurrences
        )
        return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:16]


type MemberPair = frozenset[tuple[str, int, str]]


def member_identity(core: SignatureCore) -> tuple[str, int, str]:
    return core.file, core.start_line, core.symbol


def shared_blocks(
    cores: Sequence[SignatureCore],
    *,
    related: Collection[MemberPair] = frozenset(),
    policy: BlockPolicy = BLOCK_POLICY,
) -> list[SharedBlock]:
    """Blocks shared by two or more functions, longest first.

    A run that is the whole of both functions is a whole-function clone, and
    `related` pairs were already compared as whole functions; both are left to
    the clone stages. Test and non-test functions are never mixed.
    """

    by_keys: dict[tuple[str, ...], list[BlockOccurrence]] = defaultdict(list)
    for group in _comparable_groups(cores, policy):
        for left, left_start, right, right_start, length in _runs(group, policy):
            pair = frozenset((member_identity(group[left]), member_identity(group[right])))
            occurrences = (
                BlockOccurrence(group[left], left_start, length),
                BlockOccurrence(group[right], right_start, length),
            )
            if pair in related or any(item.line_count < policy.min_lines for item in occurrences):
                continue
            by_keys[group[left].statement_keys[left_start : left_start + length]].extend(
                occurrences
            )
    by_members: dict[frozenset[tuple[str, int, str]], list[BlockOccurrence]] = defaultdict(list)
    for found in by_keys.values():
        by_members[frozenset(member_identity(item.member) for item in found)].extend(found)
    blocks = [SharedBlock(_without_overlaps(items)) for items in by_members.values()]
    return sorted(
        blocks,
        key=lambda block: (-block.statement_count, member_identity(block.occurrences[0].member)),
    )


def _without_overlaps(occurrences: list[BlockOccurrence]) -> tuple[BlockOccurrence, ...]:
    """Longest first, drop any occurrence overlapping a kept one in the same function."""

    kept: list[BlockOccurrence] = []
    for item in sorted(
        occurrences, key=lambda item: (-item.length, member_identity(item.member), item.start)
    ):
        if not any(
            other.member is item.member
            and other.start < item.start + item.length
            and item.start < other.start + other.length
            for other in kept
        ):
            kept.append(item)
    return tuple(sorted(kept, key=lambda item: (member_identity(item.member), item.start)))


def _comparable_groups(
    cores: Sequence[SignatureCore], policy: BlockPolicy
) -> Iterator[list[SignatureCore]]:
    groups: dict[tuple[str, bool], list[SignatureCore]] = defaultdict(list)
    for core in sorted(cores, key=lambda item: (item.file, item.start_line, item.symbol)):
        keys = core.statement_keys
        if len(keys) >= policy.min_statements and len(core.statement_spans) == len(keys):
            groups[(core.language_family.value, core.role in TEST_ROLES)].append(core)
    yield from (groups[key] for key in sorted(groups))


def _runs(group: list[SignatureCore], policy: BlockPolicy) -> Iterator[_Run]:
    """Longest common runs of statement keys between pairs that share a rare window."""

    width = policy.min_statements
    windows: dict[tuple[str, ...], list[tuple[int, int]]] = defaultdict(list)
    for member, core in enumerate(group):
        keys = core.statement_keys
        for start in range(_first_code_statement(core), len(keys) - width + 1):
            windows[keys[start : start + width]].append((member, start))
    seen: set[_Run] = set()
    for hits in windows.values():
        if not 1 < len({member for member, _ in hits}) <= policy.max_window_df:
            continue
        if len(set(group[hits[0][0]].statement_keys[hits[0][1] : hits[0][1] + width])) < (
            policy.min_distinct_statements
        ):
            continue
        for (left, left_start), (right, right_start) in combinations(hits, 2):
            if left == right:
                continue
            run = _maximal_run(group[left], group[right], left_start, right_start)
            key = (left, run[0], right, run[1], run[2])
            if key in seen or _whole_function(group[left], group[right], run[2]):
                continue
            seen.add(key)
            yield key


def _maximal_run(
    left_core: SignatureCore, right_core: SignatureCore, left_start: int, right_start: int
) -> tuple[int, int, int]:
    left, right = left_core.statement_keys, right_core.statement_keys
    left_first, right_first = _first_code_statement(left_core), _first_code_statement(right_core)
    while (
        left_start > left_first
        and right_start > right_first
        and left[left_start - 1] == right[right_start - 1]
    ):
        left_start, right_start = left_start - 1, right_start - 1
    length = 0
    while (
        left_start + length < len(left)
        and right_start + length < len(right)
        and left[left_start + length] == right[right_start + length]
    ):
        length += 1
    return left_start, right_start, length


def _first_code_statement(core: SignatureCore) -> int:
    """Skip a leading docstring or directive: its key matches every other one."""

    return int(core.statement_sequence[:1] == (StatementKind.EXPR.value,))


def _whole_function(left: SignatureCore, right: SignatureCore, length: int) -> bool:
    return length == _code_statement_count(left) == _code_statement_count(right)


def _code_statement_count(core: SignatureCore) -> int:
    return len(core.statement_keys) - _first_code_statement(core)


__all__ = ["BlockOccurrence", "MemberPair", "SharedBlock", "member_identity", "shared_blocks"]
