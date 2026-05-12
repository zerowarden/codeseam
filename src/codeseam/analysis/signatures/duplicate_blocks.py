from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from codeseam.analysis.signatures.model import (
    DuplicateBlockOccurrence,
    IntraFunctionDuplicateBlock,
)
from codeseam.platform import sha256_text

DUPLICATE_BLOCK_SCHEMA = "codeseam.intra_function_duplicate_block.v1"
MAX_DUPLICATE_BLOCK_GROUPS = 3
MAX_DUPLICATE_BLOCK_LINES = 20
MAX_DUPLICATE_BLOCK_STATEMENTS = 4
MIN_DUPLICATE_BLOCK_LINES = 3
MIN_DUPLICATE_BLOCK_OCCURRENCES = 2


@dataclass(frozen=True, slots=True)
class DuplicateBlockCandidate:
    kind: str
    normalized_shape: str
    statement_count: int
    line_count: int
    occurrence: DuplicateBlockOccurrence


def duplicate_blocks_from_candidates(
    candidates: Iterable[DuplicateBlockCandidate],
) -> tuple[IntraFunctionDuplicateBlock, ...]:
    """Group exact repeated local blocks from language-specific syntax facts.

    Adapters decide what a candidate block is and how to normalize it. This
    shared helper only groups equal normalized shapes and keeps compact line
    evidence for scoring. That makes the detector cheap and portable: no tree
    edit distance, no cross-function search, and no language policy here.
    """

    by_fingerprint: dict[str, list[DuplicateBlockCandidate]] = defaultdict(list)
    for candidate in candidates:
        if candidate.normalized_shape:
            by_fingerprint[_fingerprint(candidate.normalized_shape)].append(candidate)
    groups: list[IntraFunctionDuplicateBlock] = []
    for fingerprint, items in by_fingerprint.items():
        if len(items) < MIN_DUPLICATE_BLOCK_OCCURRENCES:
            continue
        groups.append(
            IntraFunctionDuplicateBlock(
                fingerprint=fingerprint,
                kind=_group_kind(items),
                statement_count=max(item.statement_count for item in items),
                line_count=max(item.line_count for item in items),
                occurrences=tuple(item.occurrence for item in items),
            )
        )
    return tuple(
        sorted(
            groups,
            key=lambda item: (-len(item.occurrences), -item.line_count, item.fingerprint),
        )[:MAX_DUPLICATE_BLOCK_GROUPS]
    )


def duplicate_block_candidate(
    *,
    kind: str,
    normalized_shape: str,
    statement_count: int,
    start_line: int,
    end_line: int,
) -> DuplicateBlockCandidate | None:
    """Build a bounded local-duplicate candidate from adapter syntax facts.

    The limits are deliberately small and language-neutral. This detector is a
    cheap local clone signal, not a replacement for relation scoring or tree
    edit distance.
    """

    if not normalized_shape or not duplicate_block_bounds_ok(
        statement_count=statement_count,
        start_line=start_line,
        end_line=end_line,
    ):
        return None
    line_count = end_line - start_line + 1
    return DuplicateBlockCandidate(
        kind=kind,
        normalized_shape=normalized_shape,
        statement_count=statement_count,
        line_count=line_count,
        occurrence=DuplicateBlockOccurrence(
            start_line=start_line,
            end_line=end_line,
            source=kind,
        ),
    )


def duplicate_block_bounds_ok(
    *,
    statement_count: int,
    start_line: int,
    end_line: int,
) -> bool:
    line_count = end_line - start_line + 1
    return (
        start_line > 0
        and statement_count > 0
        and statement_count <= MAX_DUPLICATE_BLOCK_STATEMENTS
        and line_count >= MIN_DUPLICATE_BLOCK_LINES
        and line_count <= MAX_DUPLICATE_BLOCK_LINES
    )


def _fingerprint(normalized_shape: str) -> str:
    return sha256_text(f"{DUPLICATE_BLOCK_SCHEMA}\n{normalized_shape}")


def _group_kind(items: list[DuplicateBlockCandidate]) -> str:
    kinds = {item.kind for item in items}
    return next(iter(kinds)) if len(kinds) == 1 else "mixed_control_block"


__all__ = [
    "DuplicateBlockCandidate",
    "duplicate_block_bounds_ok",
    "duplicate_block_candidate",
    "duplicate_blocks_from_candidates",
]
