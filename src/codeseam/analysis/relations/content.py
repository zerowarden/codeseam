"""Content-based candidate pairs, independent of signature shape and size.

Signature-shape buckets only compare functions with identical signatures, and
only small ones. This stage indexes every function's structural shingles and
pairs functions that share several *rare* shingles (or an identical body),
verified by shingle Jaccard. Verified edges are grouped into bounded components
that become content clusters.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from itertools import combinations

from codeseam.analysis.relations.models import MemberFeatureCache, MemberFeatures
from codeseam.analysis.relations.policy import CONTENT_POLICY
from codeseam.analysis.relations.shingles import structural_shingles
from codeseam.analysis.signatures import SignatureAnalysis
from codeseam.platform import jaccard

type MemberKey = tuple[str, int, str]
type ContentEdge = tuple[SignatureAnalysis, SignatureAnalysis]

TEST_ROLES = frozenset({"test", "fixture"})


def member_key(member: SignatureAnalysis) -> MemberKey:
    core = member.core
    return core.file, core.start_line, core.symbol


def content_components(
    members: Sequence[SignatureAnalysis],
    *,
    seen: set[frozenset[MemberKey]],
    split_test: bool = True,
) -> list[list[ContentEdge]]:
    """Group verified content edges into components, skipping already-compared pairs."""

    edges: list[tuple[float, ContentEdge]] = []
    for group in _language_groups(members).values():
        edges.extend(_content_edges(group, seen=seen, split_test=split_test))
    edges.sort(key=lambda item: (-item[0], member_key(item[1][0]), member_key(item[1][1])))
    return _bounded_components([edge for _, edge in edges])


def _language_groups(
    members: Sequence[SignatureAnalysis],
) -> dict[str, list[SignatureAnalysis]]:
    groups: dict[str, list[SignatureAnalysis]] = {}
    for member in sorted(members, key=member_key):
        groups.setdefault(member.core.language_family.value, []).append(member)
    return groups


def _content_edges(
    members: list[SignatureAnalysis],
    *,
    seen: set[frozenset[MemberKey]],
    split_test: bool,
) -> list[tuple[float, ContentEdge]]:
    policy = CONTENT_POLICY
    cache = MemberFeatureCache(members)
    features = [cache.get(member) for member in members]
    shingles = [structural_shingles(item) for item in features]
    frequency = Counter(shingle for item in shingles for shingle in item)
    indexed = [
        index
        for index, item in enumerate(features)
        if len(item.statements) >= policy.min_statements
        and len(shingles[index]) >= policy.min_shingles
    ]
    shared: Counter[tuple[int, int]] = Counter()
    postings: dict[str, list[int]] = {}
    for index in indexed:
        for shingle in shingles[index]:
            if 1 < frequency[shingle] <= policy.rare_shingle_max_df:
                postings.setdefault(shingle, []).append(index)
    for indexes in postings.values():
        shared.update(combinations(indexes, 2))
    exact = _exact_body_pairs(features, indexed)
    scored: dict[int, list[tuple[float, int]]] = {}
    rare_pairs = {pair for pair, n in shared.items() if n >= policy.min_shared_rare_shingles}
    for pair in sorted(exact | rare_pairs):
        left, right = pair
        if not _comparable(members[left], members[right], seen=seen, split_test=split_test):
            continue
        similarity = 1.0 if pair in exact else jaccard(set(shingles[left]), set(shingles[right]))
        if similarity < policy.min_jaccard:
            continue
        scored.setdefault(left, []).append((similarity, right))
        scored.setdefault(right, []).append((similarity, left))
    kept: dict[tuple[int, int], float] = {}
    for index, neighbours in scored.items():
        for similarity, other in sorted(neighbours, key=lambda item: (-item[0], item[1]))[
            : policy.neighbor_limit
        ]:
            kept[(min(index, other), max(index, other))] = similarity
    return [
        (similarity, (members[left], members[right]))
        for (left, right), similarity in sorted(kept.items())
    ]


def _exact_body_pairs(features: list[MemberFeatures], indexed: list[int]) -> set[tuple[int, int]]:
    by_hash: dict[str, list[int]] = {}
    for index in indexed:
        if body_hash := features[index].body_hash:
            by_hash.setdefault(body_hash, []).append(index)
    return {
        pair
        for indexes in by_hash.values()
        for pair in combinations(indexes[: CONTENT_POLICY.rare_shingle_max_df], 2)
    }


def _comparable(
    left: SignatureAnalysis,
    right: SignatureAnalysis,
    *,
    seen: set[frozenset[MemberKey]],
    split_test: bool,
) -> bool:
    if frozenset((member_key(left), member_key(right))) in seen:
        return False
    left_test, right_test = left.core.role in TEST_ROLES, right.core.role in TEST_ROLES
    return not (split_test and left_test != right_test)


def _bounded_components(edges: list[ContentEdge]) -> list[list[ContentEdge]]:
    """Union strongest edges first; refuse merges that would exceed the size limit."""

    parent: dict[MemberKey, MemberKey] = {}
    size: dict[MemberKey, int] = {}

    def find(key: MemberKey) -> MemberKey:
        parent.setdefault(key, key)
        size.setdefault(key, 1)
        while parent[key] != key:
            key = parent[key]
        return key

    accepted: list[ContentEdge] = []
    for edge in edges:
        left, right = find(member_key(edge[0])), find(member_key(edge[1]))
        if left != right:
            if size[left] + size[right] > CONTENT_POLICY.component_member_limit:
                continue
            parent[left] = right
            size[right] += size[left]
        accepted.append(edge)
    groups: dict[MemberKey, list[ContentEdge]] = {}
    for edge in accepted:
        groups.setdefault(find(member_key(edge[0])), []).append(edge)
    return sorted(
        groups.values(),
        key=lambda group: min(member_key(member) for edge in group for member in edge),
    )


__all__ = ["ContentEdge", "content_components", "member_key"]
