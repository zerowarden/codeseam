from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from codeseam.analysis.findings.models import SemanticEvidenceMetrics

type CallTargetIdentity = tuple[str, str]


class SemanticEnrichmentRunLike(Protocol):
    @property
    def results(self) -> Iterable[object]: ...


@dataclass(frozen=True, slots=True)
class SemanticEvidenceIndex:
    """Lookup table from upstream semantic enrichment to finding metrics.

    The semantic provider stage owns compiler/language-service calls and cache
    lookup. Finding construction receives its completed run and reduces it to
    typed, language-neutral evidence. The assessment stack then scores only
    these compact counts. That keeps detection/fit/risk/action generic and
    prevents scoring code from depending on TypeScript, Rust, Swift, or any
    provider-specific AST shape.
    """

    items_by_signature_id: dict[str, object]

    @classmethod
    def from_run(cls, run: SemanticEnrichmentRunLike | None) -> SemanticEvidenceIndex:
        if run is None:
            return cls({})
        return cls(
            {
                str(signature_id): item
                for result in getattr(run, "results", ())
                for item in getattr(result, "items", ())
                if (signature_id := getattr(item, "signature_id", ""))
            }
        )

    def metrics_for_members(
        self,
        members: Iterable[object],
        *,
        relation_pairs: Iterable[object] = (),
    ) -> SemanticEvidenceMetrics:
        items = _unique_items(self.items_by_signature_id, members)
        if not items:
            return SemanticEvidenceMetrics()
        pair_items = [
            (left, right)
            for pair in relation_pairs
            if (left := self._item_for(getattr(pair, "left", None))) is not None
            and (right := self._item_for(getattr(pair, "right", None))) is not None
        ]
        return SemanticEvidenceMetrics(
            unresolved_item_count=sum(1 for item in items if not getattr(item, "resolved", False)),
            ambiguous_ownership_count=sum(
                1 for item in items if getattr(item, "ownership_ambiguous", False)
            ),
            declaration_only_count=sum(
                1 for item in items if getattr(item, "declaration_only", False)
            ),
            same_overload_group_pair_count=sum(
                1 for left, right in pair_items if _same_overload_group(left, right)
            ),
            shared_call_target_pair_count=sum(
                1 for left, right in pair_items if _shared_call_target(left, right)
            ),
            divergent_call_target_pair_count=sum(
                1 for left, right in pair_items if _divergent_call_target(left, right)
            ),
        )

    def _item_for(self, member: object) -> object | None:
        signature_id = _signature_id(member)
        if not signature_id:
            return None
        return self.items_by_signature_id.get(signature_id)


def _unique_items(
    items_by_signature_id: dict[str, object],
    members: Iterable[object],
) -> tuple[object, ...]:
    seen: set[str] = set()
    items: list[object] = []
    for member in members:
        signature_id = _signature_id(member)
        if not signature_id or signature_id in seen:
            continue
        if item := items_by_signature_id.get(signature_id):
            seen.add(signature_id)
            items.append(item)
    return tuple(items)


def _signature_id(member: object) -> str:
    source = getattr(member, "signature", member)
    return str(getattr(source, "signature_id", "") or "")


def _same_overload_group(left: object, right: object) -> bool:
    return bool(
        (left_group := getattr(left, "overload_group_id", ""))
        and (right_group := getattr(right, "overload_group_id", ""))
        and left_group == right_group
    )


def _shared_call_target(left: object, right: object) -> bool:
    return bool(
        _target_identities(getattr(left, "call_targets", ()))
        & _target_identities(getattr(right, "call_targets", ()))
    )


def _divergent_call_target(left: object, right: object) -> bool:
    left_by_token = _targets_by_token(getattr(left, "call_targets", ()))
    right_by_token = _targets_by_token(getattr(right, "call_targets", ()))
    for token in left_by_token.keys() & right_by_token.keys():
        if left_by_token[token].isdisjoint(right_by_token[token]):
            return True
    return False


def _target_identities(call_targets: Iterable[object]) -> set[CallTargetIdentity]:
    return {
        identity for target in call_targets if (identity := _target_identity(target)) is not None
    }


def _targets_by_token(
    call_targets: Iterable[object],
) -> dict[str, set[CallTargetIdentity]]:
    by_token: dict[str, set[CallTargetIdentity]] = {}
    for target in call_targets:
        identity = _target_identity(target)
        token = str(getattr(target, "call_token", "") or "")
        if identity is None or not token:
            continue
        by_token.setdefault(token, set()).add(identity)
    return by_token


def _target_identity(target: object) -> CallTargetIdentity | None:
    if not getattr(target, "resolved", False):
        return None
    name = str(getattr(target, "symbol_name", "") or "")
    file = str(getattr(target, "declaration_file", "") or "")
    if not name and not file:
        return None
    return name, file


__all__ = ["SemanticEvidenceIndex"]
