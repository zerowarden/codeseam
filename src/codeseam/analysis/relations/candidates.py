from __future__ import annotations

from collections.abc import Sequence
from itertools import combinations

from codeseam.analysis.relations.models import MemberFeatureCache, MemberFeatures, MemberInput
from codeseam.analysis.relations.policy import STRUCTURAL_POLICY
from codeseam.analysis.relations.shingles import structural_shingles
from codeseam.platform import cached_identifier_tokens, increment_stat, jaccard

EXACT_BODY_ESTIMATE = 2.0
type FeatureEntry = tuple[MemberInput, MemberFeatures]
type Buckets = dict[tuple[str, ...], list[FeatureEntry]]
type CandidatePairMap = dict[
    tuple[tuple[str, ...], tuple[str, ...]], tuple[FeatureEntry, FeatureEntry]
]


def relation_candidate_members(
    members: Sequence[MemberInput],
    feature_cache: MemberFeatureCache | None = None,
) -> list[MemberInput]:
    """Members compact enough for bucketed comparison, in location order.

    Nothing is dropped for lack of room and no size class is favoured; larger
    functions are compared by the content stage instead.
    """
    cache = feature_cache or MemberFeatureCache(members)
    return [
        member
        for member, features in sorted(
            cache.entries(members), key=lambda item: _location_key(item[1])
        )
        if _candidate_member_is_structural(features)
    ]


def relation_candidate_pairs(
    candidates: Sequence[MemberInput],
    feature_cache: MemberFeatureCache | None = None,
    stats: dict[str, int] | None = None,
) -> list[tuple[MemberInput, MemberInput]]:
    """Bucketed pairs, ranked by estimated content similarity before the pair limit."""
    cache = feature_cache or MemberFeatureCache(candidates)
    entries = sorted(cache.entries(candidates), key=lambda item: _location_key(item[1]))
    buckets: Buckets = {}
    for entry in entries:
        for key in _candidate_bucket_keys(entry[1]):
            buckets.setdefault(key, []).append(entry)
    pairs = _bucket_pairs(buckets, stats)
    shingles = {
        _member_identity(features): structural_shingles(features) for _, features in entries
    }
    ranked = sorted(
        pairs.items(),
        key=lambda item: (-_content_estimate(item[1][0][1], item[1][1][1], shingles), item[0]),
    )
    limit = STRUCTURAL_POLICY.structural_pair_candidate_limit
    increment_stat(stats, "candidate_pairs_truncated_count", max(0, len(ranked) - limit))
    return [(left, right) for _, ((left, _), (right, _)) in ranked[:limit]]


def oversized_exact_body_pairs(
    members: Sequence[MemberInput],
    feature_cache: MemberFeatureCache | None = None,
    stats: dict[str, int] | None = None,
) -> list[tuple[MemberInput, MemberInput]]:
    """Pair identical bodies that are too large for fuzzy structural matching.

    Size limits bound the cost of fuzzy comparison; they must not hide exact
    clones, which are cheap to find and the most valuable to consolidate.
    """
    cache = feature_cache or MemberFeatureCache(members)
    buckets: Buckets = {}
    for entry in sorted(cache.entries(members), key=lambda item: _location_key(item[1])):
        features = entry[1]
        if (
            features.body_hash
            and _has_structural_features(features)
            and not _candidate_member_is_structural(features)
        ):
            buckets.setdefault(("body_hash", features.body_hash), []).append(entry)
    return [(left, right) for (left, _), (right, _) in _bucket_pairs(buckets, stats).values()]


def _bucket_pairs(buckets: Buckets, stats: dict[str, int] | None) -> CandidatePairMap:
    limit = STRUCTURAL_POLICY.structural_bucket_member_limit
    pairs: CandidatePairMap = {}
    for key in sorted(buckets):
        members = buckets[key]
        increment_stat(
            stats, "candidate_bucket_members_truncated_count", max(0, len(members) - limit)
        )
        for left, right in combinations(members[:limit], 2):
            pairs.setdefault(_candidate_pair_key(left[1], right[1]), (left, right))
    return dict(sorted(pairs.items()))


def _content_estimate(
    left: MemberFeatures,
    right: MemberFeatures,
    shingles: dict[tuple[str, ...], frozenset[str]],
) -> float:
    """Identical bodies first, then structural-shingle overlap."""
    if left.body_hash and left.body_hash == right.body_hash:
        return EXACT_BODY_ESTIMATE
    return jaccard(set(shingles[_member_identity(left)]), set(shingles[_member_identity(right)]))


def _candidate_bucket_keys(features: MemberFeatures) -> list[tuple[str, ...]]:
    role = features.role
    name = features.normalized_name
    tokens = cached_identifier_tokens(name)
    keys: list[tuple[str, ...]] = []
    if name:
        keys.append(("name", name))
        keys.append(("role_name", role, name))
    if tokens:
        keys.append(("token_prefix", tokens[0]))
        keys.append(("role_token_prefix", role, tokens[0]))
    for token in features.calls[: STRUCTURAL_POLICY.summary_limit]:
        if token:
            keys.append(("role_call", role, token))
    if payload_key := _payload_builder_bucket_key(features):
        keys.append(payload_key)
    if features.body_hash:
        keys.append(("body_hash", features.body_hash))
    return list(dict.fromkeys(keys))


def _candidate_pair_key(
    left_features: MemberFeatures,
    right_features: MemberFeatures,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    identities = sorted((_member_identity(left_features), _member_identity(right_features)))
    return identities[0], identities[1]


def _payload_builder_bucket_key(features: MemberFeatures) -> tuple[str, ...] | None:
    sequence = features.statements
    if not sequence or not sequence[-1].startswith("RETURN:"):
        return None
    if not any(item.startswith("ASSIGN:") for item in sequence):
        return None
    target = _first_call_target(features)
    if not target:
        return None
    return ("payload_builder_terminal_call", features.role, target)


def _first_call_target(features: MemberFeatures) -> str:
    for token in features.calls:
        target = token.split("(args=", 1)[0]
        if target:
            return target
    return ""


def _has_structural_features(features: MemberFeatures) -> bool:
    return bool(features.statements and (features.body_hash or features.calls))


def _candidate_member_is_structural(features: MemberFeatures) -> bool:
    return (
        _has_structural_features(features)
        and 0 < len(features.statements) <= STRUCTURAL_POLICY.max_statement_count
        and features.tree_node_count <= STRUCTURAL_POLICY.max_tree_nodes
    )


def _location_key(features: MemberFeatures) -> tuple[str, int, str]:
    member = features.member
    return member.file, member.start_line, member.symbol


def _member_identity(features: MemberFeatures) -> tuple[str, ...]:
    member = features.member
    return (
        member.file,
        str(member.start_line),
        member.symbol,
        member.signature_id,
        member.function_id,
    )
