from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import lru_cache

from codeseam.analysis.relations.clones import clone_classification_for
from codeseam.analysis.relations.members import has_error_evidence
from codeseam.analysis.relations.models import (
    ArgumentNormalization,
    CloneClassificationInput,
    DeltaKind,
    MemberFeatureCache,
    MemberFeatures,
    MemberInput,
    MemberRef,
    PairActionInput,
    RefactorAction,
    RefactorShapeInput,
    RelationBasis,
    RelationBasisInput,
    RelationFlags,
    RelationKind,
    RelationPair,
    RelationScores,
    SequenceComparison,
    SimilarityScores,
    TreeComparison,
    TreeEditDecision,
    sequence_skeleton_summary,
)
from codeseam.analysis.relations.normalization import argument_normalization_relation_features
from codeseam.analysis.relations.policy import PAIR_POLICY, STRUCTURAL_POLICY, TREE_EDIT_POLICY
from codeseam.analysis.relations.scoring import (
    abstraction_cost_components_features,
    component_sum,
    confidence_score,
    refactorability_components_features,
    refactorability_kind,
    relatedness_score,
    risk_score,
)
from codeseam.analysis.relations.shapes import refactor_shape_from_features
from codeseam.analysis.relations.similarity import (
    TREE_EDIT_PRODUCT_LIMIT_SOURCE,
    call_multiset_similarity_features,
    graph_similarity_features,
    parameter_use_similarity_features,
    same_call_multiset_features,
    sequence_alignment_features,
    should_compare_tree_features,
    tree_comparison_features,
    tree_edit_product_exceeds_limit,
    tree_proxy_comparison_features,
)
from codeseam.analysis.relations.unification import SequenceSkeleton, anti_unify_sequences
from codeseam.platform import increment_stat, similarity_ratio

ActionBuilder = Callable[[PairActionInput], list[RefactorAction]]
TreeComparisonProvider = Callable[[MemberFeatures, MemberFeatures], TreeComparison]


@dataclass
class TreeEditBudget:
    limit: int = TREE_EDIT_POLICY.run_budget
    used: int = 0

    def try_consume(self) -> bool:
        if self.used >= self.limit:
            return False
        self.used += 1
        return True


def relation_pairs(
    candidate_pairs: Sequence[tuple[MemberInput, MemberInput]],
    *,
    action_builder: ActionBuilder,
    feature_cache: MemberFeatureCache | None = None,
    stats: dict[str, int] | None = None,
    tree_edit_budget: TreeEditBudget | None = None,
) -> list[RelationPair]:
    increment_stat(stats, "candidate_pair_count", len(candidate_pairs))
    if not candidate_pairs:
        return []
    cache = feature_cache or MemberFeatureCache(
        [member for pair in candidate_pairs for member in pair]
    )
    candidate_members = [member for pair in candidate_pairs for member in pair]
    feature_by_member_id = {
        id(member): features for member, features in cache.entries(candidate_members)
    }
    candidates = [
        (
            left,
            right,
            feature_by_member_id[id(left)],
            feature_by_member_id[id(right)],
        )
        for left, right in candidate_pairs
    ]
    pairs: list[RelationPair] = []
    for _, _, left_features, right_features in candidates:
        pair = relation_pair_from_features(
            left_features,
            right_features,
            action_builder=action_builder,
            stats=stats,
            tree_edit_budget=tree_edit_budget,
        )
        if pair is not None:
            pairs.append(pair)
            increment_stat(stats, "scored_relation_pair_count")
    result = sorted(
        pairs,
        key=lambda item: (
            -item.scores.relatedness,
            -item.scores.refactorability,
            item.left.file,
            item.right.file,
        ),
    )[: PAIR_POLICY.relation_pair_limit]
    increment_stat(stats, "relation_pair_count", len(result))
    return result


def structural_duplicate_pairs(relation_pairs: list[RelationPair]) -> list[RelationPair]:
    return [
        pair
        for pair in relation_pairs
        if pair.same_role
        and pair.scores.name >= STRUCTURAL_POLICY.name_similarity_threshold
        and pair.tree.tree_similarity >= STRUCTURAL_POLICY.tree_similarity_threshold
        and pair.relation_kind
        in {
            RelationKind.BODY_IDENTICAL,
            RelationKind.BODY_PARAMETERIZED,
        }
    ][: STRUCTURAL_POLICY.structural_pair_limit]


def relation_pair_from_features(  # noqa: PLR0913
    left_features: MemberFeatures,
    right_features: MemberFeatures,
    *,
    action_builder: ActionBuilder,
    stats: dict[str, int] | None = None,
    tree_edit_budget: TreeEditBudget | None = None,
    tree_comparison_provider: TreeComparisonProvider = tree_comparison_features,
) -> RelationPair | None:
    left_name = left_features.normalized_name
    right_name = right_features.normalized_name
    name_similarity = _name_similarity(left_name, right_name)
    sequence = sequence_alignment_features(left_features, right_features)
    parameter_similarity = parameter_use_similarity_features(left_features, right_features)
    call_similarity = call_multiset_similarity_features(left_features, right_features)
    graph = graph_similarity_features(left_features, right_features)
    normalization = argument_normalization_relation_features(left_features, right_features)
    cheap_scores = SimilarityScores(
        name=name_similarity,
        tree=0.0,
        parameter=parameter_similarity,
        call=call_similarity,
        sequence=sequence.sequence_similarity,
        graph=graph,
    )
    tree_gate = tree_edit_decision(
        left_features,
        right_features,
        cheap_scores,
        has_argument_normalization=normalization.is_detected,
    )
    if tree_gate.reject:
        increment_stat(stats, "pre_tree_rejected_count")
        return None
    if tree_gate.compare_edit_distance and tree_gate.tree_distance_source == "body_hash":
        increment_stat(stats, "tree_edit_body_hash_count")
        tree = tree_comparison_provider(left_features, right_features)
    elif tree_gate.compare_edit_distance and _tree_edit_budget_available(
        stats,
        tree_edit_budget,
    ):
        increment_stat(stats, "tree_edit_requested_count")
        tree = tree_comparison_provider(left_features, right_features)
    else:
        increment_stat(
            stats,
            "tree_edit_budget_exhausted_count"
            if tree_gate.compare_edit_distance
            else "tree_edit_skipped_count",
        )
        tree = tree_proxy_comparison_features(
            left_features,
            right_features,
            proxy_similarity=tree_gate.proxy_tree_similarity,
            source=tree_gate.tree_distance_source,
        )
    tree_similarity = tree.tree_similarity
    similarity_scores = cheap_scores.with_tree(tree_similarity)
    relatedness = relatedness_score(similarity_scores)
    if normalization.is_detected:
        relatedness = max(relatedness, PAIR_POLICY.min_argument_normalization_relatedness)
    if relatedness < PAIR_POLICY.relatedness_minimum:
        return None
    deltas = delta_kinds(left_features, right_features, parameter_similarity, normalization)
    risk = risk_score(deltas)
    anti = anti_unification_from_features(
        sequence,
        left_features,
        right_features,
    )
    cost_components = abstraction_cost_components_features(
        left_features,
        right_features,
        anti_unification=anti,
        deltas=deltas,
        parameter_similarity=parameter_similarity,
    )
    cost = component_sum(cost_components)
    refactor_components = refactorability_components_features(
        left_features,
        right_features,
        sequence=sequence,
        anti_unification=anti,
        abstraction_cost=cost,
    )
    refactorability = component_sum(refactor_components)
    if normalization.is_detected:
        refactorability = max(
            refactorability,
            PAIR_POLICY.min_argument_normalization_refactorability,
        )
    basis = relation_basis(
        left_features,
        right_features,
        RelationBasisInput(
            sequence=sequence,
            tree=tree,
            parameter_similarity=parameter_similarity,
            normalization=normalization,
        ),
    )
    relation = relation_kind(basis, left_features, right_features)
    confidence = confidence_score(relatedness, risk)
    scores = RelationScores(
        name=name_similarity,
        parameter_use=parameter_similarity,
        call_multiset=call_similarity,
        graph=graph,
        relatedness=relatedness,
        refactorability=refactorability,
        abstraction_cost=cost,
        confidence=confidence,
        risk=risk,
    )
    classification = clone_classification_for(
        CloneClassificationInput(
            relation_kind=relation,
            scores=scores,
            flags=basis.flags,
            tree_similarity=tree_similarity,
            tree_distance_source=tree.tree_distance_source,
            parameter_similarity=parameter_similarity,
            call_similarity=call_similarity,
            sequence=sequence,
            anti_unification=anti,
            deltas=deltas,
            refactorability=refactorability,
            abstraction_cost=cost,
            argument_normalization=normalization,
        )
    )
    shape = refactor_shape_from_features(
        left_features,
        right_features,
        shape_input=RefactorShapeInput(
            anti_unification=anti,
            relation_kind=relation,
            clone_type=classification.clone_type,
            default_action=classification.default_action,
            abstraction_cost=cost,
            delta_kinds=deltas,
        ),
    )
    left_ref = feature_member_ref(left_features)
    right_ref = feature_member_ref(right_features)
    action_context = PairActionInput(
        left=left_ref,
        right=right_ref,
        relation_kind=relation,
        sequence=sequence,
        normalization=normalization,
        refactorability=refactorability,
        abstraction_cost=cost,
        confidence=confidence,
        deltas=deltas,
    )
    return RelationPair(
        left=left_ref,
        right=right_ref,
        scores=scores,
        tree=tree,
        sequence=sequence,
        refactorability_components=refactor_components,
        abstraction_cost_components=cost_components,
        relation_kind=relation,
        relation_basis=basis,
        flags=basis.flags,
        relation_kinds=tuple(relation_labels(relation, basis)),
        clone_family=classification.clone_type,
        clone_type=classification.clone_type,
        recommended_action=classification.default_action,
        clone_classification=classification,
        refactorability_kind=refactorability_kind(refactorability),
        delta_kinds=tuple(deltas),
        anti_unification=anti,
        anti_unification_summary=sequence_skeleton_summary(anti),
        refactor_action_candidates=tuple(action_builder(action_context)),
        same_role=left_features.role == right_features.role,
        role=left_features.role,
        max_body_line_count=max(left_features.body_line_count, right_features.body_line_count),
        min_body_line_count=min(left_features.body_line_count, right_features.body_line_count),
        refactor_shape=None if shape.renderable_skeleton.suppressed else shape,
    )


def feature_member_ref(features: MemberFeatures) -> MemberRef:
    return features.ref


def relation_kind(
    basis: RelationBasis,
    left_features: MemberFeatures,
    right_features: MemberFeatures,
) -> RelationKind:
    prefix = basis.shared_prefix_length
    suffix = basis.shared_suffix_length
    lcs = basis.lcs_length
    same_tree = basis.flags.same_tree
    relation = RelationKind.NONE
    if left_features.body_hash and left_features.body_hash == right_features.body_hash:
        left_name = left_features.normalized_name
        right_name = right_features.normalized_name
        relation = (
            RelationKind.BODY_IDENTICAL
            if left_name == right_name
            else RelationKind.BODY_PARAMETERIZED
        )
    elif basis.argument_normalization_wrapper:
        relation = RelationKind.ARGUMENT_NORMALIZATION_WRAPPER
    elif same_tree and left_features.literal_shapes != right_features.literal_shapes:
        relation = RelationKind.SAME_SKELETON_DIFFERENT_LITERALS
    elif same_tree and left_features.call_counts != right_features.call_counts:
        relation = RelationKind.SAME_SKELETON_DIFFERENT_CALLEES
    elif basis.flags.parameter_flow_match and basis.flags.control_vector_differs:
        relation = RelationKind.SAME_ARGUMENT_FLOW_DIFFERENT_CONTROL
    elif prefix > 0 and suffix > 0 and _has_wrapper_evidence(basis):
        relation = RelationKind.COMMON_WRAPPER_DIFFERENT_CORE
    elif lcs > prefix + suffix:
        relation = RelationKind.SAME_CORE_DIFFERENT_WRAPPER
    elif prefix > 0:
        relation = RelationKind.COMMON_PREFIX_DIVERGENT_TAIL
    elif suffix > 0:
        relation = RelationKind.COMMON_SUFFIX_DIVERGENT_SETUP
    elif same_call_multiset_features(left_features, right_features) and (
        left_features.calls != right_features.calls
    ):
        relation = RelationKind.SAME_CALL_SET_DIFFERENT_ORDER
    return relation


def relation_basis(
    left_features: MemberFeatures,
    right_features: MemberFeatures,
    context: RelationBasisInput,
) -> RelationBasis:
    left_calls = left_features.call_counts
    right_calls = right_features.call_counts
    left_return = left_features.return_signature
    right_return = right_features.return_signature
    left_error = left_features.error_shape
    right_error = right_features.error_shape
    flags = RelationFlags(
        body_hash_match=bool(
            left_features.body_hash and left_features.body_hash == right_features.body_hash
        ),
        same_signature_shape=left_features.member.shape_hash == right_features.member.shape_hash,
        same_tree=(
            context.tree.tree_distance_source in {"body_hash", "ordered_tree_edit_distance"}
            and context.tree.tree_similarity >= STRUCTURAL_POLICY.tree_similarity_threshold
        ),
        literal_shapes_differ=left_features.literal_shapes != right_features.literal_shapes,
        call_multiset_differs=left_calls != right_calls,
        same_call_multiset=bool(left_calls and left_calls == right_calls),
        control_vector_differs=left_features.control_set != right_features.control_set,
        parameter_flow_match=(context.parameter_similarity >= PAIR_POLICY.parameter_flow_threshold),
        same_return_shape=bool(left_return and left_return == right_return),
        same_error_shape=bool(has_error_evidence(left_error) and left_error == right_error),
        shared_argument_flow_through_tail=context.sequence.shared_argument_flow_in_tail,
    )
    return RelationBasis(
        flags=flags,
        argument_normalization=context.normalization,
        shared_prefix_length=context.sequence.common_prefix_length,
        shared_suffix_length=context.sequence.common_suffix_length,
        lcs_length=context.sequence.lcs_length,
    )


def relation_labels(primary: RelationKind, basis: RelationBasis) -> list[RelationKind]:
    candidates: list[RelationKind] = []
    if primary is not RelationKind.NONE:
        candidates.append(primary)
    if basis.flags.body_hash_match:
        candidates.append(RelationKind.BODY_IDENTICAL)
    if basis.argument_normalization_wrapper:
        candidates.append(RelationKind.ARGUMENT_NORMALIZATION_WRAPPER)
    if basis.flags.same_tree and basis.flags.literal_shapes_differ:
        candidates.append(RelationKind.SAME_SKELETON_DIFFERENT_LITERALS)
    if basis.flags.same_tree and basis.flags.call_multiset_differs:
        candidates.append(RelationKind.SAME_SKELETON_DIFFERENT_CALLEES)
    if basis.flags.parameter_flow_match and basis.flags.control_vector_differs:
        candidates.append(RelationKind.SAME_ARGUMENT_FLOW_DIFFERENT_CONTROL)
    if _has_wrapper_evidence(basis):
        candidates.append(RelationKind.COMMON_WRAPPER_DIFFERENT_CORE)
    if basis.flags.same_call_multiset:
        candidates.append(RelationKind.SAME_CALL_SET_DIFFERENT_ORDER)
    prefix = basis.shared_prefix_length
    suffix = basis.shared_suffix_length
    lcs = basis.lcs_length
    if prefix:
        candidates.append(RelationKind.COMMON_PREFIX_DIVERGENT_TAIL)
    if suffix:
        candidates.append(RelationKind.COMMON_SUFFIX_DIVERGENT_SETUP)
    if lcs > prefix + suffix:
        candidates.append(RelationKind.SAME_CORE_DIFFERENT_WRAPPER)
    return list(dict.fromkeys(candidates))


def tree_edit_decision(
    left: MemberFeatures,
    right: MemberFeatures,
    cheap_scores: SimilarityScores,
    *,
    has_argument_normalization: bool,
) -> TreeEditDecision:
    """Decide whether ordered tree edit distance is worth paying for.

    Tree edit distance is a CPU-heavy confirmation signal, not the first
    candidate generator. The gate uses already-extracted `MemberFeatures`
    and cheap pair scores to reject pairs that cannot reach the relation
    threshold, or to keep a proxy tree score when non-tree evidence is already
    sufficient. Full edit distance is reserved for exact body hashes and pairs
    where the tree result can materially affect classification or ranking.
    """
    if left.body_hash and left.body_hash == right.body_hash:
        return _tree_decision(compare=True, proxy=1.0, source="body_hash")
    proxy = cheap_scores.sequence
    best_possible = _relatedness_with_tree(cheap_scores, tree_similarity=1.0)
    if best_possible < PAIR_POLICY.relatedness_minimum and not has_argument_normalization:
        return _tree_decision(
            reject=True,
            proxy=proxy,
            source="pre_tree_best_possible_below_threshold",
        )
    if tree_edit_product_exceeds_limit(left, right):
        return _tree_decision(
            proxy=proxy,
            source=TREE_EDIT_PRODUCT_LIMIT_SOURCE,
        )
    if not should_compare_tree_features(left, right):
        return _tree_decision(
            proxy=proxy,
            source="tree_edit_skipped_size_limit",
        )
    cheap_relatedness = _relatedness_with_tree(cheap_scores, tree_similarity=proxy)
    if cheap_relatedness >= PAIR_POLICY.relatedness_minimum and not _high_value_tree_pair(
        left,
        right,
        cheap_scores,
        has_argument_normalization=has_argument_normalization,
    ):
        return _tree_decision(
            proxy=proxy,
            source="tree_edit_skipped_cheap_evidence_sufficient",
        )
    return _tree_decision(compare=True, proxy=proxy, source="ordered_tree_edit_distance")


def _high_value_tree_pair(
    left: MemberFeatures,
    right: MemberFeatures,
    cheap_scores: SimilarityScores,
    *,
    has_argument_normalization: bool,
) -> bool:
    if has_argument_normalization:
        return True
    if left.statements and left.statements == right.statements:
        return True
    sequence_similarity = cheap_scores.sequence
    if (
        left.role == right.role
        and cheap_scores.name >= TREE_EDIT_POLICY.name_threshold
        and sequence_similarity > 0
    ):
        return True
    if sequence_similarity >= TREE_EDIT_POLICY.sequence_threshold:
        return True
    if (
        cheap_scores.call >= TREE_EDIT_POLICY.call_threshold
        and sequence_similarity >= TREE_EDIT_POLICY.call_sequence_threshold
    ):
        return True
    return (
        cheap_scores.parameter >= PAIR_POLICY.parameter_flow_threshold
        and cheap_scores.graph >= TREE_EDIT_POLICY.graph_threshold
        and sequence_similarity >= TREE_EDIT_POLICY.graph_sequence_threshold
    )


def _relatedness_with_tree(
    cheap_scores: SimilarityScores,
    *,
    tree_similarity: float,
) -> float:
    return relatedness_score(cheap_scores.with_tree(tree_similarity))


def _tree_decision(
    *,
    compare: bool = False,
    reject: bool = False,
    proxy: float,
    source: str,
) -> TreeEditDecision:
    return TreeEditDecision(
        compare_edit_distance=compare,
        reject=reject,
        proxy_tree_similarity=proxy,
        tree_distance_source=source,
    )


def _tree_edit_budget_available(
    stats: dict[str, int] | None,
    budget: TreeEditBudget | None,
) -> bool:
    cluster_available = (
        stats is None or stats.get("tree_edit_requested_count", 0) < TREE_EDIT_POLICY.cluster_budget
    )
    return cluster_available and (budget is None or budget.try_consume())


@lru_cache(maxsize=4096)
def _name_similarity(left: str, right: str) -> float:
    """Cheap relation-name gate before the Levenshtein fallback.

    Normalized symbol names are a ranking signal, not proof of equivalence. Most
    candidate pairs have weakly related names, often sharing only a generic token
    such as "is" or "payload". For those, token Jaccard is good enough as a cheap
    score. We keep dynamic-programming edit distance for plausible near matches:
    prefix/suffix variants and names with substantial token overlap.
    """
    if left == right:
        return 1.0
    if not left or not right or _name_length_gap_too_large(left, right):
        return 0.0
    left_tokens = frozenset(left.split())
    right_tokens = frozenset(right.split())
    if not left_tokens or not right_tokens:
        return similarity_ratio(left, right)
    overlap = left_tokens & right_tokens
    if not overlap:
        return 0.0
    token_similarity = len(overlap) / len(left_tokens | right_tokens)
    if token_similarity < PAIR_POLICY.name_gate_token_similarity_threshold and not (
        _one_name_contains_the_other(left, right)
    ):
        return round(token_similarity, 4)
    return similarity_ratio(left, right)


def _name_length_gap_too_large(left: str, right: str) -> bool:
    return abs(len(left) - len(right)) > max(len(left), len(right)) * 0.5


def _one_name_contains_the_other(left: str, right: str) -> bool:
    return (
        left.startswith(right)
        or right.startswith(left)
        or left.endswith(right)
        or right.endswith(left)
    )


def _has_wrapper_evidence(basis: RelationBasis) -> bool:
    prefix = basis.shared_prefix_length
    suffix = basis.shared_suffix_length
    if not prefix or not suffix:
        return False
    return bool(
        prefix + suffix >= PAIR_POLICY.min_wrapper_stable_edge_count
        or basis.flags.same_tree
        or basis.flags.same_return_shape
        or basis.flags.same_error_shape
        or basis.flags.shared_argument_flow_through_tail
    )


def delta_kinds(
    left_features: MemberFeatures,
    right_features: MemberFeatures,
    parameter_similarity: float,
    normalization: ArgumentNormalization | None = None,
) -> tuple[DeltaKind, ...]:
    checks = [
        (
            left_features.parameter_default_roles != right_features.parameter_default_roles,
            (DeltaKind.DEFAULT_ARGUMENT,),
        ),
        (
            left_features.literal_shapes != right_features.literal_shapes,
            (DeltaKind.LITERAL_VALUE,),
        ),
        (
            left_features.receiver_shapes != right_features.receiver_shapes,
            (DeltaKind.RECEIVER_SHAPE,),
        ),
        (
            normalization is not None and normalization.is_detected,
            (DeltaKind.ARGUMENT_NORMALIZATION,),
        ),
        (
            _control_count(left_features, "WITH") != _control_count(right_features, "WITH"),
            (DeltaKind.EXTRA_CONTEXT_MANAGER,),
        ),
        (
            _statement_count(left_features, "ASSIGN") != _statement_count(right_features, "ASSIGN"),
            (DeltaKind.EXTRA_LOCAL_TEMPORARY, DeltaKind.EXTRA_ASSIGNMENT),
        ),
        (
            _last_statement(left_features) != _last_statement(right_features),
            (DeltaKind.EXTRA_TERMINAL_CALL,),
        ),
        (left_features.call_counts != right_features.call_counts, (DeltaKind.CALLEE_NAME,)),
        (
            parameter_similarity < PAIR_POLICY.parameter_flow_threshold,
            (DeltaKind.ARGUMENT_FLOW,),
        ),
        (left_features.control_set != right_features.control_set, (DeltaKind.CONTROL_FLOW,)),
        (
            _control_count(left_features, "TRY") != _control_count(right_features, "TRY"),
            (DeltaKind.ERROR_HANDLING,),
        ),
        (
            _control_count(left_features, "LOOP") != _control_count(right_features, "LOOP"),
            (DeltaKind.LOOP,),
        ),
        (
            left_features.return_signature != right_features.return_signature,
            (DeltaKind.RETURN_VALUE,),
        ),
    ]
    deltas = [delta for condition, values in checks if condition for delta in values]
    return tuple(sorted(set(deltas), key=lambda delta: delta.value))


def anti_unification_from_features(
    sequence: SequenceComparison,
    left_features: MemberFeatures,
    right_features: MemberFeatures,
) -> SequenceSkeleton:
    skeleton = anti_unify_sequences(
        list(left_features.statements),
        list(right_features.statements),
        left_id=left_features.member.binding_key,
        right_id=right_features.member.binding_key,
    )
    if sequence.shared_argument_flow_in_tail and not skeleton.shared_param_flow_through_holes:
        return SequenceSkeleton(
            template=skeleton.template,
            hole_bindings=skeleton.hole_bindings,
            stable_statement_count=skeleton.stable_statement_count,
            stable_node_ratio=skeleton.stable_node_ratio,
            common_prefix_length=skeleton.common_prefix_length,
            common_suffix_length=skeleton.common_suffix_length,
            common_prefix_ratio=skeleton.common_prefix_ratio,
            hole_count=skeleton.hole_count,
            max_hole_size=skeleton.max_hole_size,
            hole_size_variance=skeleton.hole_size_variance,
            shared_param_flow_through_holes=True,
        )
    return skeleton


def _last_statement(features: MemberFeatures) -> str:
    return features.statements[-1] if features.statements else ""


def _statement_count(features: MemberFeatures, prefix: str) -> int:
    return sum(item.startswith(prefix) for item in features.statements)


def _control_count(features: MemberFeatures, kind: str) -> int:
    return features.control_vector.count(kind)
