from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import combinations

from codeseam.analysis.relations.models import MemberFeatureCache, MemberFeatures, MemberInput
from codeseam.analysis.relations.policy import (
    STRUCTURAL_POLICY,
    TREE_EDIT_POLICY,
)
from codeseam.analysis.relations.shingles import structural_shingles
from codeseam.platform import (
    DEFAULT_LSH_BANDS,
    DEFAULT_MINHASH_SIZE,
    cached_identifier_tokens,
    hash64_band,
    jaccard,
    lcs_length,
    lsh_band_keys,
    minhash_signature,
)

TINY_STATEMENT_COUNT = 5
SMALL_STATEMENT_COUNT = 12
LSH_CLUSTER_MEMBER_THRESHOLD = 24
LSH_MIN_SHINGLE_COUNT = 3
LSH_MAX_BUCKET_MEMBER_COUNT = STRUCTURAL_POLICY.structural_bucket_member_limit
LSH_MIN_SHINGLE_JACCARD = 0.55
LSH_PAIR_CAP_TRIGGER = STRUCTURAL_POLICY.structural_pair_candidate_limit * 2
type FeatureEntry = tuple[MemberInput, MemberFeatures]
type CandidatePairMap = dict[
    tuple[tuple[str, ...], tuple[str, ...]], tuple[FeatureEntry, FeatureEntry]
]


@dataclass(frozen=True, slots=True)
class ExactCandidateSimilarity:
    shingle_jaccard: float
    call_jaccard: float
    statement_lcs: float
    graph_jaccard: float


def relation_candidate_members(
    members: Sequence[MemberInput],
    feature_cache: MemberFeatureCache | None = None,
) -> list[MemberInput]:
    cache = feature_cache or MemberFeatureCache(members)
    entries = cache.entries(members)
    return [
        member
        for member, features in sorted(
            entries,
            key=lambda item: (
                -_candidate_member_score(item[1]),
                _location_key(item[1]),
            ),
        )
        if _candidate_member_is_structural(features)
    ][: STRUCTURAL_POLICY.structural_cluster_member_limit]


def relation_candidate_pairs(
    candidates: Sequence[MemberInput],
    feature_cache: MemberFeatureCache | None = None,
) -> list[tuple[MemberInput, MemberInput]]:
    cache = feature_cache or MemberFeatureCache(candidates)
    entries = cache.entries(candidates)
    deterministic_pairs = _deterministic_bucket_pairs(entries)
    pairs: CandidatePairMap = {}
    _merge_pairs(pairs, deterministic_pairs)
    _merge_pairs(pairs, _exact_body_hash_pairs(entries))
    if _should_run_lsh(entries, deterministic_pairs):
        _merge_pairs(pairs, _lsh_candidate_pairs(entries))
    scored_pairs = [
        (
            _cheap_pair_score(left_features, right_features),
            pair_key,
            (left, right),
        )
        for pair_key, ((left, left_features), (right, right_features)) in pairs.items()
    ]
    return [
        pair
        for _, _, pair in sorted(
            scored_pairs,
            key=lambda item: (-item[0], item[1]),
        )[: STRUCTURAL_POLICY.structural_pair_candidate_limit]
    ]


def _should_run_lsh(
    entries: Sequence[FeatureEntry],
    deterministic_pairs: Sequence[tuple[FeatureEntry, FeatureEntry]],
) -> bool:
    return (
        len(entries) >= LSH_CLUSTER_MEMBER_THRESHOLD
        and len(deterministic_pairs) >= LSH_PAIR_CAP_TRIGGER
    )


def _merge_pairs(
    target: CandidatePairMap, pairs: Sequence[tuple[FeatureEntry, FeatureEntry]]
) -> None:
    for left, right in pairs:
        pair_key = _candidate_pair_key(left[1], right[1])
        target.setdefault(pair_key, _ordered_pair(left, right))


def _ordered_pair(left: FeatureEntry, right: FeatureEntry) -> tuple[FeatureEntry, FeatureEntry]:
    left_key = _member_identity(left[1])
    right_key = _member_identity(right[1])
    return (left, right) if left_key <= right_key else (right, left)


def _deterministic_bucket_pairs(
    entries: Sequence[FeatureEntry],
) -> list[tuple[FeatureEntry, FeatureEntry]]:
    buckets: dict[tuple[str, ...], list[FeatureEntry]] = {}
    for member, features in entries:
        entry = (member, features)
        for key in _candidate_bucket_keys(member, features):
            buckets.setdefault(key, []).append(entry)

    pairs: CandidatePairMap = {}
    for key in sorted(buckets):
        members = buckets[key][: STRUCTURAL_POLICY.structural_bucket_member_limit]
        for left, right in combinations(members, 2):
            pair_key = _candidate_pair_key(left[1], right[1])
            pairs.setdefault(pair_key, (left, right))
    return [pairs[key] for key in sorted(pairs)]


def _exact_body_hash_pairs(
    entries: Sequence[FeatureEntry],
) -> list[tuple[FeatureEntry, FeatureEntry]]:
    buckets: dict[str, list[FeatureEntry]] = {}
    for entry in entries:
        body_hash = entry[1].body_hash
        if body_hash:
            buckets.setdefault(body_hash, []).append(entry)

    pairs: CandidatePairMap = {}
    for body_hash in sorted(buckets):
        for left, right in combinations(buckets[body_hash], 2):
            pair_key = _candidate_pair_key(left[1], right[1])
            pairs.setdefault(pair_key, (left, right))
    return [pairs[key] for key in sorted(pairs)]


def _candidate_bucket_keys(member: MemberInput, features: MemberFeatures) -> list[tuple[str, ...]]:
    del member
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
    return list(dict.fromkeys(keys))


def _lsh_candidate_pairs(
    entries: Sequence[FeatureEntry],
) -> list[tuple[FeatureEntry, FeatureEntry]]:
    shingle_by_key: dict[tuple[str, ...], frozenset[str]] = {}
    buckets: dict[tuple[str, int, int], list[FeatureEntry]] = {}
    for entry in entries:
        shingles = structural_shingles(entry[1])
        if len(shingles) < LSH_MIN_SHINGLE_COUNT:
            continue
        shingle_by_key[_member_identity(entry[1])] = shingles
        signature = minhash_signature(shingles, size=DEFAULT_MINHASH_SIZE)
        family = _language_family(entry)
        for band_index, band in lsh_band_keys(signature, bands=DEFAULT_LSH_BANDS):
            buckets.setdefault((family, band_index, hash64_band(band)), []).append(entry)

    pairs: CandidatePairMap = {}
    for key in sorted(buckets):
        members = buckets[key]
        if len(members) > LSH_MAX_BUCKET_MEMBER_COUNT:
            continue
        for left, right in combinations(members, 2):
            if not _lsh_pair_verified(left[1], right[1], shingle_by_key):
                continue
            pair_key = _candidate_pair_key(left[1], right[1])
            pairs.setdefault(pair_key, (left, right))
    return [pairs[key] for key in sorted(pairs)]


def _lsh_pair_verified(
    left: MemberFeatures,
    right: MemberFeatures,
    shingle_by_key: dict[tuple[str, ...], frozenset[str]],
) -> bool:
    similarity = _exact_candidate_similarity(left, right, shingle_by_key)
    if similarity.shingle_jaccard >= LSH_MIN_SHINGLE_JACCARD:
        return True
    if similarity.statement_lcs >= TREE_EDIT_POLICY.sequence_threshold:
        return True
    if (
        similarity.call_jaccard >= TREE_EDIT_POLICY.call_threshold
        and similarity.statement_lcs >= TREE_EDIT_POLICY.call_sequence_threshold
    ):
        return True
    return (
        similarity.graph_jaccard >= TREE_EDIT_POLICY.graph_threshold
        and similarity.statement_lcs >= TREE_EDIT_POLICY.graph_sequence_threshold
    )


def _exact_candidate_similarity(
    left: MemberFeatures,
    right: MemberFeatures,
    shingle_by_key: dict[tuple[str, ...], frozenset[str]],
) -> ExactCandidateSimilarity:
    left_shingles = shingle_by_key.get(_member_identity(left), frozenset())
    right_shingles = shingle_by_key.get(_member_identity(right), frozenset())
    return ExactCandidateSimilarity(
        shingle_jaccard=jaccard(set(left_shingles), set(right_shingles)),
        call_jaccard=_call_overlap_score(left.call_set, right.call_set),
        statement_lcs=_statement_lcs_similarity(left, right),
        graph_jaccard=jaccard(set(left.graph_features), set(right.graph_features)),
    )


def _statement_lcs_similarity(left: MemberFeatures, right: MemberFeatures) -> float:
    if not left.statements or not right.statements:
        return 0.0
    max_len = max(len(left.statements), len(right.statements), 1)
    return round(lcs_length(list(left.statements), list(right.statements)) / max_len, 4)


def _language_family(entry: FeatureEntry) -> str:
    member, features = entry
    if family := getattr(member, "language_family", ""):
        return getattr(family, "value", family).lower()
    return features.member.language.lower()


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


def _cheap_pair_score(
    left_features: MemberFeatures,
    right_features: MemberFeatures,
) -> float:
    score = _call_overlap_score(left_features.call_set, right_features.call_set)
    if left_features.body_hash and left_features.body_hash == right_features.body_hash:
        score += 3.0
    if left_features.normalized_name == right_features.normalized_name:
        score += 2.0
    if left_features.role == right_features.role:
        score += 1.0
    if _same_statements(left_features, right_features):
        score += 1.5
    return score


def _call_overlap_score(left_calls: frozenset[str], right_calls: frozenset[str]) -> float:
    if not left_calls and not right_calls:
        return 0.0
    smaller, larger = (
        (left_calls, right_calls)
        if len(left_calls) <= len(right_calls)
        else (right_calls, left_calls)
    )
    overlap = sum(1 for token in smaller if token in larger)
    return overlap / (len(left_calls) + len(right_calls) - overlap)


def _same_statements(left_features: MemberFeatures, right_features: MemberFeatures) -> bool:
    return (
        left_features.statement_fingerprint == right_features.statement_fingerprint
        and left_features.statements == right_features.statements
    )


def _candidate_member_score(features: MemberFeatures) -> float:
    score = 0.0
    if features.body_hash:
        score += 3.0
    if features.normalized_name:
        score += 1.0
    score += min(2.0, len(features.calls) * 0.25)
    statement_count = len(features.statements)
    if 0 < statement_count <= TINY_STATEMENT_COUNT:
        score += 1.0
    elif statement_count <= SMALL_STATEMENT_COUNT:
        score += 0.5
    if features.role in {"source", "test"}:
        score += 0.25
    return score


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
