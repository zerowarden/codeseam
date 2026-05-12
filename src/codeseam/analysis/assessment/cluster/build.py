from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import combinations

from codeseam.analysis.assessment.cluster.models import Cluster, ClusterMember
from codeseam.analysis.assessment.definitions import ExtractionConfidence
from codeseam.analysis.relations import EvidenceKind, RelationKind
from codeseam.analysis.relations.enrichment import (
    RelationFeatureHydrator,
    RelationPairBuilder,
    enrich_signature_cluster,
)
from codeseam.analysis.relations.normalization import (
    has_argument_normalization_transform,
    shared_operation_candidate,
)
from codeseam.analysis.relations.pairs import TreeEditBudget
from codeseam.analysis.signatures import (
    AdapterId,
    LanguageFamily,
    NormalizationLevel,
    SignatureAnalysis,
    SignatureCore,
    signature_analysis_from_core,
)
from codeseam.caveat_msg import (
    ADAPTER_WRAPPER_SIGNATURE_CAVEATS,
    ANALOGOUS_SIGNATURE_CAVEATS,
    BROAD_TEST_SIGNATURE_CAVEATS,
    BROAD_UNKNOWN_SIGNATURE_CAVEATS,
    SIGNATURE_CAVEATS,
)
from codeseam.platform import cached_identifier_tokens, sha256_text

ADAPTER_WRAPPER_CLUSTER_LIMIT = 40
ADAPTER_WRAPPER_BUCKET_MEMBER_LIMIT = 12
BROAD_SIGNATURE_CLUSTER_MEMBER_THRESHOLD = 500
BROAD_TEST_SPLIT_MEMBER_THRESHOLD = 40
BROAD_TEST_SUMMARY_MEMBER_THRESHOLD = 30
MIN_CLUSTER_MEMBERS = 2
TEST_RELATION_ROLES = frozenset({"test", "fixture"})


def build_clusters(
    signatures: Sequence[SignatureAnalysis | SignatureCore],
    *,
    relation_pair_builder: RelationPairBuilder | None = None,
    split_test: bool = True,
    feature_hydrator: RelationFeatureHydrator | None = None,
) -> tuple[Cluster, ...]:
    tree_edit_budget = TreeEditBudget()
    analyses = [
        signature
        if isinstance(signature, SignatureAnalysis)
        else signature_analysis_from_core(signature)
        for signature in signatures
    ]
    grouped: dict[tuple[str, str], list[SignatureAnalysis]] = defaultdict(list)
    for signature in analyses:
        core = signature.core
        grouped[(core.language, core.shape_hash)].append(signature)
    same_language: list[Cluster] = []
    for language, shape_hash, members in _same_language_groups(grouped):
        same_language.extend(
            _same_language_clusters(
                start_index=len(same_language) + 1,
                language=language,
                shape_hash=shape_hash,
                members=members,
                relation_pair_builder=relation_pair_builder,
                tree_edit_budget=tree_edit_budget,
                split_test=split_test,
                feature_hydrator=feature_hydrator,
            )
        )
    adapter_wrappers = _adapter_wrapper_clusters(
        analyses,
        start_index=len(same_language) + 1,
        relation_pair_builder=relation_pair_builder,
        tree_edit_budget=tree_edit_budget,
        feature_hydrator=feature_hydrator,
    )
    analogous = _analogous_clusters(
        analyses,
        start_index=len(same_language) + len(adapter_wrappers) + 1,
        relation_pair_builder=relation_pair_builder,
        tree_edit_budget=tree_edit_budget,
    )
    return tuple([*same_language, *adapter_wrappers, *analogous])


def _same_language_groups(
    grouped: dict[tuple[str, str], list[SignatureAnalysis]],
) -> list[tuple[str, str, list[SignatureAnalysis]]]:
    return [
        (language, shape_hash, members)
        for (language, shape_hash), members in sorted(grouped.items(), key=lambda item: item[0])
        if len(members) > 1
    ]


def _same_language_clusters(  # noqa: PLR0913
    *,
    start_index: int,
    language: str,
    shape_hash: str,
    members: list[SignatureAnalysis],
    relation_pair_builder: RelationPairBuilder | None,
    tree_edit_budget: TreeEditBudget,
    split_test: bool,
    feature_hydrator: RelationFeatureHydrator | None,
) -> list[Cluster]:
    if split_test and _mixed_test_source_broad_cluster(members):
        return _test_role_split_clusters(
            start_index=start_index,
            language=language,
            shape_hash=shape_hash,
            members=members,
            relation_pair_builder=relation_pair_builder,
            tree_edit_budget=tree_edit_budget,
            feature_hydrator=feature_hydrator,
        )
    return _same_language_clusters_unsplit(
        start_index=start_index,
        language=language,
        shape_hash=shape_hash,
        members=members,
        relation_pair_builder=relation_pair_builder,
        tree_edit_budget=tree_edit_budget,
        split_test=split_test,
        feature_hydrator=feature_hydrator,
    )


def _same_language_clusters_unsplit(  # noqa: PLR0913
    *,
    start_index: int,
    language: str,
    shape_hash: str,
    members: list[SignatureAnalysis],
    relation_pair_builder: RelationPairBuilder | None,
    tree_edit_budget: TreeEditBudget,
    split_test: bool,
    feature_hydrator: RelationFeatureHydrator | None,
) -> list[Cluster]:
    if not _broad_unknown_cluster(members):
        if split_test and _broad_test_cluster(members):
            return _broad_test_clusters(
                start_index=start_index,
                language=language,
                members=members,
                relation_pair_builder=relation_pair_builder,
                tree_edit_budget=tree_edit_budget,
                feature_hydrator=feature_hydrator,
            )
        return [
            _cluster(
                start_index,
                language,
                shape_hash,
                members,
                relation_pair_builder=relation_pair_builder,
                tree_edit_budget=tree_edit_budget,
                feature_hydrator=feature_hydrator,
            )
        ]
    return _broad_unknown_clusters(
        start_index=start_index,
        language=language,
        members=members,
        relation_pair_builder=relation_pair_builder,
        tree_edit_budget=tree_edit_budget,
        feature_hydrator=feature_hydrator,
    )


def _mixed_test_source_broad_cluster(members: list[SignatureAnalysis]) -> bool:
    if len(members) < BROAD_TEST_SPLIT_MEMBER_THRESHOLD:
        return False
    return len(_test_role_buckets(members)) > 1


def _test_role_split_clusters(  # noqa: PLR0913
    *,
    start_index: int,
    language: str,
    shape_hash: str,
    members: list[SignatureAnalysis],
    relation_pair_builder: RelationPairBuilder | None,
    tree_edit_budget: TreeEditBudget,
    feature_hydrator: RelationFeatureHydrator | None,
) -> list[Cluster]:
    buckets: dict[str, list[SignatureAnalysis]] = defaultdict(list)
    for member in members:
        buckets[_test_role(member)].append(member)
    clusters: list[Cluster] = []
    for role, group in sorted(buckets.items()):
        if len(group) < MIN_CLUSTER_MEMBERS:
            continue
        clusters.extend(
            _same_language_clusters_unsplit(
                start_index=start_index + len(clusters),
                language=language,
                shape_hash=sha256_text("|".join((shape_hash, "split_test", role))),
                members=sorted(group, key=_signature_location_key),
                relation_pair_builder=relation_pair_builder,
                tree_edit_budget=tree_edit_budget,
                split_test=True,
                feature_hydrator=feature_hydrator,
            )
        )
    return clusters


def _test_role(member: SignatureAnalysis) -> str:
    return "test" if member.core.role in TEST_RELATION_ROLES else "source"


def _broad_unknown_cluster(members: list[SignatureAnalysis]) -> bool:
    if len(members) <= BROAD_SIGNATURE_CLUSTER_MEMBER_THRESHOLD:
        return False
    return _unknown_shape(members[0].core.canonical_shape)


def _broad_test_cluster(members: list[SignatureAnalysis]) -> bool:
    if len(members) < BROAD_TEST_SUMMARY_MEMBER_THRESHOLD:
        return False
    return _test_role_buckets(members) == {"test"}


def _test_role_buckets(members: list[SignatureAnalysis]) -> set[str]:
    return _member_buckets(
        members,
        lambda member: "test" if member.core.role in TEST_RELATION_ROLES else "source",
    )


def _member_buckets[T](
    members: list[SignatureAnalysis],
    bucket: Callable[[SignatureAnalysis], T],
) -> set[T]:
    return {bucket(member) for member in members}


def _unknown_shape(shape: str) -> bool:
    return "UNKNOWN" in shape and "fn(UNKNOWN" in shape and ")->UNKNOWN" in shape


def _broad_test_clusters(  # noqa: PLR0913
    *,
    start_index: int,
    language: str,
    members: list[SignatureAnalysis],
    relation_pair_builder: RelationPairBuilder | None,
    tree_edit_budget: TreeEditBudget,
    feature_hydrator: RelationFeatureHydrator | None,
) -> list[Cluster]:
    duplicate_groups, remaining = _exact_body_duplicate_groups(members)
    clusters: list[Cluster] = []
    for group in duplicate_groups:
        body_hash = group[0].core.body_shape_hash
        clusters.append(
            _cluster(
                start_index + len(clusters),
                language,
                sha256_text("|".join((members[0].core.shape_hash, "test_exact_body", body_hash))),
                sorted(group, key=_signature_location_key),
                scope="broad_test_signature_exact_body",
                candidate_scope="exact_body_hash_before_broad_test_degradation",
                extra_candidate_methods=["exact_body_hash_preserved"],
                relation_pair_builder=relation_pair_builder,
                tree_edit_budget=tree_edit_budget,
                feature_hydrator=feature_hydrator,
            )
        )
    if len(remaining) > 1:
        clusters.append(
            _cluster(
                start_index + len(clusters),
                language,
                sha256_text("|".join((members[0].core.shape_hash, "test_summary"))),
                sorted(remaining, key=_signature_location_key),
                scope="broad_test_signature_summary",
                enrich=False,
            )
        )
    return clusters


def _broad_unknown_clusters(  # noqa: PLR0913
    *,
    start_index: int,
    language: str,
    members: list[SignatureAnalysis],
    relation_pair_builder: RelationPairBuilder | None,
    tree_edit_budget: TreeEditBudget,
    feature_hydrator: RelationFeatureHydrator | None,
) -> list[Cluster]:
    duplicate_groups, remaining = _exact_body_duplicate_groups(members)
    clusters: list[Cluster] = []
    for group in duplicate_groups:
        body_hash = group[0].core.body_shape_hash
        clusters.append(
            _cluster(
                start_index + len(clusters),
                language,
                sha256_text("|".join((members[0].core.shape_hash, "exact_body", body_hash))),
                sorted(group, key=_signature_location_key),
                scope="broad_unknown_signature_exact_body",
                candidate_scope="exact_body_hash_before_broad_unknown_degradation",
                extra_candidate_methods=["exact_body_hash_preserved"],
                relation_pair_builder=relation_pair_builder,
                tree_edit_budget=tree_edit_budget,
                feature_hydrator=feature_hydrator,
            )
        )
    if len(remaining) > 1:
        # Broad UNKNOWN clusters are intentionally not split into many normal
        # relation clusters. That exploded cluster/candidate counts on large
        # repos. After the exact duplicate fast lane, the remaining weak
        # recurrence stays visible as one summary-only family.
        clusters.append(
            _cluster(
                start_index + len(clusters),
                language,
                sha256_text("|".join((members[0].core.shape_hash, "weak_summary"))),
                sorted(remaining, key=_signature_location_key),
                scope="broad_unknown_signature_summary",
                enrich=False,
            )
        )
    return clusters


def _exact_body_duplicate_groups(
    members: list[SignatureAnalysis],
) -> tuple[list[list[SignatureAnalysis]], list[SignatureAnalysis]]:
    """Preserve exact duplicates before broad UNKNOWN degradation.

    Broad UNKNOWN signature shapes are weak typing evidence, so large groups are
    split or summarized before relation scoring. Exact body hashes are different:
    they are cheap, strong clone evidence and should remain visible even when
    the surrounding UNKNOWN cluster is too broad to enrich globally.
    """
    buckets: dict[str, list[SignatureAnalysis]] = defaultdict(list)
    for member in members:
        if member.core.body_shape_hash:
            buckets[member.core.body_shape_hash].append(member)
    duplicate_groups = [
        sorted(group, key=_signature_location_key)
        for _, group in sorted(buckets.items())
        if len(group) > 1
    ]
    duplicate_ids = {member.core.signature_id for group in duplicate_groups for member in group}
    remaining = [member for member in members if member.core.signature_id not in duplicate_ids]
    return duplicate_groups, remaining


def _cluster(  # noqa: PLR0913
    index: int,
    language: str,
    shape_hash: str,
    members: list[SignatureAnalysis],
    *,
    scope: str = "same_language",
    enrich: bool = True,
    base_evidence_kind: str = EvidenceKind.SIGNATURE_SHAPE_CLUSTER,
    candidate_scope: str = "within_signature_shape_bucket",
    extra_candidate_methods: list[str] | None = None,
    relation_pair_builder: RelationPairBuilder | None = None,
    tree_edit_budget: TreeEditBudget | None = None,
    feature_hydrator: RelationFeatureHydrator | None = None,
) -> Cluster:
    enrichment = (
        enrich_signature_cluster(
            members,
            base_evidence_kind=base_evidence_kind,
            candidate_scope=candidate_scope,
            extra_candidate_methods=extra_candidate_methods or [],
            relation_pair_builder=relation_pair_builder,
            tree_edit_budget=tree_edit_budget,
            feature_hydrator=feature_hydrator,
        )
        if enrich
        else None
    )
    languages, adapters, families = _scope_metadata(members)
    canonical_shape, cluster_hash = _cluster_shape_and_hash(shape_hash, members, base_evidence_kind)
    return Cluster(
        cluster_id=f"sigcl_{index:06d}",
        language=language,
        shape_hash=cluster_hash,
        canonical_shape=canonical_shape,
        members=tuple(_cluster_member(member, scope) for member in members),
        overlaps={"review_targets": ()},
        review_relevance=_review_relevance(scope),
        priority_hint="info",
        non_claims=tuple(_non_claims(scope, base_evidence_kind)),
        cluster_scope=scope,
        languages=languages,
        language_count=len(languages),
        language_families=families,
        language_family_count=len(families),
        adapters=adapters,
        adapter_count=len(adapters),
        min_extraction_confidence=_min_confidence(members),
        normalization_level=_normalization_level(members),
        enrichment=enrichment,
    )


def _adapter_wrapper_clusters(
    signatures: list[SignatureAnalysis],
    *,
    start_index: int,
    relation_pair_builder: RelationPairBuilder | None,
    tree_edit_budget: TreeEditBudget,
    feature_hydrator: RelationFeatureHydrator | None,
) -> list[Cluster]:
    clusters: list[Cluster] = []
    for left, right in _adapter_wrapper_pairs(signatures, feature_hydrator):
        cluster = _cluster(
            start_index + len(clusters),
            left.core.language,
            "",
            sorted([left, right], key=_signature_location_key),
            base_evidence_kind=EvidenceKind.ARGUMENT_NORMALIZATION_WRAPPER,
            candidate_scope="cross_signature_argument_normalization_bucket",
            extra_candidate_methods=["argument_normalization_wrapper_bucket"],
            relation_pair_builder=relation_pair_builder,
            tree_edit_budget=tree_edit_budget,
            feature_hydrator=feature_hydrator,
        )
        if _has_argument_normalization_pair(cluster):
            clusters.append(cluster)
        if len(clusters) >= ADAPTER_WRAPPER_CLUSTER_LIMIT:
            break
    return clusters


def _adapter_wrapper_pairs(
    signatures: list[SignatureAnalysis],
    feature_hydrator: RelationFeatureHydrator | None,
) -> list[tuple[SignatureAnalysis, SignatureAnalysis]]:
    buckets: dict[tuple[str, ...], list[SignatureAnalysis]] = defaultdict(list)
    for signature in signatures:
        if not _adapter_wrapper_candidate(signature):
            continue
        for key in _adapter_wrapper_bucket_keys(signature):
            buckets[key].append(signature)
    pairs: dict[
        tuple[tuple[str, ...], tuple[str, ...]],
        tuple[SignatureAnalysis, SignatureAnalysis],
    ] = {}
    for key in sorted(buckets):
        members = sorted(buckets[key], key=_signature_location_key)[
            :ADAPTER_WRAPPER_BUCKET_MEMBER_LIMIT
        ]
        for left, right in combinations(members, 2):
            if feature_hydrator is not None:
                pair_left, pair_right = feature_hydrator((left, right))
            else:
                pair_left, pair_right = left, right
            if not _adapter_wrapper_pair_candidate(pair_left, pair_right):
                continue
            identities = sorted((_member_identity(pair_left), _member_identity(pair_right)))
            pair_key = (identities[0], identities[1])
            pairs.setdefault(pair_key, (pair_left, pair_right))
    return [
        pair
        for _, pair in sorted(
            ((_adapter_wrapper_pair_score(*pair), pair) for pair in pairs.values()),
            key=lambda item: (-item[0], _member_identity(item[1][0]), _member_identity(item[1][1])),
        )
    ]


def _adapter_wrapper_candidate(member: SignatureAnalysis) -> bool:
    core = member.core
    return bool(
        core.language
        and core.return_type
        and len(core.parameters) == 1
        and core.statement_sequence == ("RETURN:ARG0",)
        and _call_tokens(member)
    )


def _adapter_wrapper_pair_candidate(
    left: SignatureAnalysis,
    right: SignatureAnalysis,
) -> bool:
    left_core = left.core
    right_core = right.core
    return bool(
        left_core.shape_hash != right_core.shape_hash
        and left_core.language == right_core.language
        and left_core.return_type == right_core.return_type
        and _first_parameter(left) != _first_parameter(right)
        and (
            has_argument_normalization_transform(left)
            or has_argument_normalization_transform(right)
        )
        and shared_operation_candidate(left, right)
    )


def _adapter_wrapper_bucket_keys(member: SignatureAnalysis) -> list[tuple[str, ...]]:
    core = member.core
    prefix = (
        core.language,
        core.role,
        core.return_type,
    )
    keys = [(*prefix, "name_token", token) for token in _symbol_tokens(member)]
    keys.extend((*prefix, "call", token) for token in _call_tokens(member))
    return list(dict.fromkeys(keys))


def _adapter_wrapper_pair_score(left: SignatureAnalysis, right: SignatureAnalysis) -> float:
    left_tokens = set(_symbol_tokens(left))
    right_tokens = set(_symbol_tokens(right))
    shared_calls = set(_call_tokens(left)) & set(_call_tokens(right))
    score = len(left_tokens & right_tokens) + min(3, len(shared_calls))
    if left.core.file == right.core.file:
        score += 2
    return float(score)


def _symbol_tokens(member: SignatureAnalysis) -> tuple[str, ...]:
    core = member.core
    return cached_identifier_tokens(core.normalized_symbol or core.symbol)


def _call_tokens(member: SignatureAnalysis) -> list[str]:
    return list(member.core.call_tokens)


def _first_parameter(member: SignatureAnalysis) -> str:
    return member.core.parameters[0] if member.core.parameters else ""


def _member_identity(member: SignatureAnalysis) -> tuple[str, ...]:
    core = member.core
    return (
        core.file,
        str(core.start_line),
        core.symbol,
        core.signature_id,
        core.function_id or "",
    )


def _signature_location_key(member: SignatureAnalysis) -> tuple[str, int, str]:
    core = member.core
    return core.file, core.start_line, core.symbol


def _has_argument_normalization_pair(cluster: Cluster) -> bool:
    pairs = cluster.enrichment.structural_relation_pairs if cluster.enrichment else ()
    return any(pair.relation_kind == RelationKind.ARGUMENT_NORMALIZATION_WRAPPER for pair in pairs)


def _cluster_shape_and_hash(
    shape_hash: str,
    members: list[SignatureAnalysis],
    base_evidence_kind: str,
) -> tuple[str, str]:
    if base_evidence_kind != EvidenceKind.ARGUMENT_NORMALIZATION_WRAPPER:
        return members[0].core.canonical_shape, shape_hash
    shapes = sorted({member.core.canonical_shape for member in members})
    canonical = "argument_normalization_wrapper(" + " <-> ".join(shapes) + ")"
    return canonical, sha256_text(canonical)


def _non_claims(scope: str, base_evidence_kind: str) -> list[str]:
    if base_evidence_kind == EvidenceKind.ARGUMENT_NORMALIZATION_WRAPPER:
        return list(ADAPTER_WRAPPER_SIGNATURE_CAVEATS)
    if scope.startswith("broad_unknown_signature_"):
        return list(BROAD_UNKNOWN_SIGNATURE_CAVEATS)
    if scope.startswith("broad_test_signature_"):
        return list(BROAD_TEST_SIGNATURE_CAVEATS)
    if scope != "same_language":
        return list(ANALOGOUS_SIGNATURE_CAVEATS)
    return list(SIGNATURE_CAVEATS)


def _analogous_clusters(
    signatures: list[SignatureAnalysis],
    *,
    start_index: int,
    relation_pair_builder: RelationPairBuilder | None,
    tree_edit_budget: TreeEditBudget,
) -> list[Cluster]:
    grouped: dict[str, list[SignatureAnalysis]] = defaultdict(list)
    for signature in signatures:
        grouped[signature.core.shape_hash].append(signature)
    clusters: list[Cluster] = []
    for shape_hash, members in sorted(grouped.items()):
        languages = {member.core.language for member in members}
        if len(languages) <= 1:
            continue
        clusters.append(
            _cluster(
                start_index + len(clusters),
                "multiple",
                shape_hash,
                sorted(members, key=_signature_location_key),
                scope=_scope_for(members),
                enrich=False,
                relation_pair_builder=relation_pair_builder,
                tree_edit_budget=tree_edit_budget,
            )
        )
    return clusters


def _scope_for(members: list[SignatureAnalysis]) -> str:
    families = _member_buckets(members, lambda member: _language_scope(member).family)
    return "same_family" if len(families) == 1 else "cross_language"


def _scope_metadata(
    members: list[SignatureAnalysis],
) -> tuple[tuple[str, ...], tuple[AdapterId, ...], tuple[LanguageFamily, ...]]:
    languages = sorted(_member_buckets(members, lambda member: member.core.language))
    adapters = sorted(
        _member_buckets(members, lambda member: _language_scope(member).adapter),
        key=lambda item: item.value,
    )
    families = sorted(
        _member_buckets(members, lambda member: _language_scope(member).family),
        key=lambda item: item.value,
    )
    return tuple(languages), tuple(adapters), tuple(families)


def _cluster_member(member: SignatureAnalysis, scope: str) -> ClusterMember:
    core = member.core
    if scope.startswith("same_language") or scope.startswith("broad_test_signature_"):
        return ClusterMember(signature=core)
    language_scope = _language_scope(member)
    return ClusterMember(
        signature=core,
        language=core.language,
        language_family=language_scope.family,
        adapter=language_scope.adapter,
    )


def _review_relevance(scope: str) -> str:
    if scope.startswith("broad_unknown_signature_"):
        return "weak_unknown_signature_recurrence"
    if scope.startswith("broad_test_signature_"):
        return "test_pattern_family"
    if scope.startswith("same_language"):
        return "signature_shape_only"
    return f"{scope}_signature_shape_observation"


@dataclass(frozen=True, slots=True)
class _LanguageScope:
    family: LanguageFamily
    adapter: AdapterId


def _language_scope(member: SignatureAnalysis) -> _LanguageScope:
    core = member.core
    return _LanguageScope(
        family=core.language_family,
        adapter=core.adapter,
    )


def _min_confidence(members: list[SignatureAnalysis]) -> ExtractionConfidence:
    values = [ExtractionConfidence.HIGH for _ in members]
    return min(
        values,
        key=lambda value: value.rank,
        default=ExtractionConfidence.UNKNOWN,
    )


def _normalization_level(members: list[SignatureAnalysis]) -> NormalizationLevel:
    if any(member.core.call_tokens for member in members):
        return NormalizationLevel.CALL
    if any(member.core.control_context_vector for member in members):
        return NormalizationLevel.CONTROL
    return NormalizationLevel.SIGNATURE
