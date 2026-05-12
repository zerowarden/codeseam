from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from codeseam.analysis.relations.models import CALLSITE_EVIDENCE_KINDS, RelationMemberContext
from codeseam.analysis.signatures import CallsitePattern
from codeseam.platform import text

CALLABLE_RETURN_RE = re.compile(r"\b(callable|Callable|function|Function)\b|=>|->")


def is_callable_return(return_type: object) -> bool:
    return bool(CALLABLE_RETURN_RE.search(text(return_type)))


def callsite_evidence_kinds(patterns: Iterable[CallsitePattern]) -> list[str]:
    kinds = (pattern.kind for pattern in patterns)
    return sorted(kind for kind in kinds if kind in CALLSITE_EVIDENCE_KINDS)


def callable_members(
    members: Sequence[RelationMemberContext],
) -> tuple[RelationMemberContext, ...]:
    return tuple(member for member in members if is_callable_return(member.return_type))


def callsite_patterns(members: Sequence[RelationMemberContext]) -> tuple[CallsitePattern, ...]:
    patterns: list[CallsitePattern] = []
    seen: set[tuple[str, str, str, int]] = set()
    for member in members:
        for pattern in member.callsite_patterns:
            key = (
                pattern.kind,
                pattern.symbol,
                pattern.file,
                pattern.line,
            )
            if key not in seen:
                patterns.append(pattern)
                seen.add(key)
    return tuple(
        sorted(
            patterns,
            key=lambda item: (
                item.file,
                item.line,
                item.kind,
            ),
        )
    )
