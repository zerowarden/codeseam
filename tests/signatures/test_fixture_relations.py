from __future__ import annotations

from typing import Any

import pytest

from codeseam.analysis import (
    AbstractionKind,
    ActionKind,
    CloneClass,
    EvidenceKind,
    RelationKind,
    abstraction_estimate,
)

from .factories import fixture_cluster_payloads, fixture_payload
from .selectors import cluster_by_shape, cluster_with_evidence, relation_pair_by_kind

MIN_EXACT_RELATEDNESS_SCORE = 0.9
MIN_EXACT_REFACTORABILITY_SCORE = 0.5
MIN_WRAPPER_CONFIDENCE_SCORE = 0.7
MIN_WRAPPER_REFACTORABILITY_SCORE = 0.6
MAX_EXACT_ABSTRACTION_COST = 0.1
MIN_DIVERGENT_ABSTRACTION_COST = 0.4
MAX_WRAPPER_ABSTRACTION_COST = 0.4
EXPECTED_DIVERGENT_CLUSTER_MEMBER_COUNT = 3
EXPECTED_PAYLOAD_BUILDER_MEMBER_COUNT = 2
EXPECTED_PAYLOAD_BUILDER_PAIR_COUNT = 1


@pytest.fixture(scope="module")
def exact_duplicate_pair() -> tuple[dict[str, Any], dict[str, Any]]:
    cluster = cluster_with_evidence(
        fixture_cluster_payloads([("small_structural_duplicate.py", "source")]),
        EvidenceKind.STRUCTURAL_DUPLICATE,
    )
    return cluster, cluster["structural_duplicate_pairs"][0]


def test_python_signature_clusters_record_structural_duplicate_identity(
    exact_duplicate_pair: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    cluster, pair = exact_duplicate_pair

    assert cluster["enrichment_schema_version"] == "codeseam.signature_cluster_enrichment.v1"
    assert cluster["cluster_confidence"] == cluster["confidence"]
    assert cluster["abstraction_kind"] == AbstractionKind.EXTRACT_HELPER
    assert pair["schema_version"] == "codeseam.structural_relation_pair.v1"
    assert pair["score_model"] == "heuristic_v1"
    assert pair["score_interpretation"] == "ranking_signal_not_probability"
    assert pair["pair_confidence"] == pair["confidence_score"]
    assert pair["same_role"] is True


def test_python_signature_clusters_score_exact_structural_duplicates(
    exact_duplicate_pair: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    _cluster, pair = exact_duplicate_pair

    assert pair["name_similarity"] == 1.0
    assert pair["tree_similarity"] == 1.0
    assert pair["tree_distance"] == 0.0
    assert pair["tree_edit_distance"] == 0
    assert pair["tree_node_count"] > 0
    assert pair["tree_distance_source"] == "body_hash"
    assert pair["relation_basis"]["body_hash_match"] is True
    assert pair["relatedness_score"] > MIN_EXACT_RELATEDNESS_SCORE
    assert pair["refactorability_score"] > MIN_EXACT_REFACTORABILITY_SCORE
    assert pair["abstraction_cost_score"] <= MAX_EXACT_ABSTRACTION_COST
    assert pair["abstraction_cost_components"]["hole_count"] == 0.0
    assert pair["refactorability_components"]["same_source_role"] > 0
    assert pair["confidence_score"] > MIN_EXACT_RELATEDNESS_SCORE
    assert pair["graph_similarity"] == 1.0
    assert pair["risk_score"] >= 0


def test_python_signature_clusters_classify_exact_structural_duplicates(
    exact_duplicate_pair: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    _cluster, pair = exact_duplicate_pair

    assert_pair_classification(
        pair,
        relation_kind=RelationKind.BODY_IDENTICAL,
        clone_type=CloneClass.TYPE_1_EXACT,
        action=ActionKind.CONSOLIDATE_CLONE,
        refactorability_kind="high",
    )
    assert pair["clone_classification"]["basis"]


def test_python_signature_clusters_emit_exact_refactor_shape(
    exact_duplicate_pair: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    _cluster, pair = exact_duplicate_pair

    assert pair["anti_unification"]["stable_node_ratio"] == 1.0
    assert pair["refactor_shape"]["abstraction_domain"] == "normalized_statement_sequence"
    assert pair["refactor_shape"]["renderable_skeleton"]["suppressed"] is False
    assert pair["refactor_shape"]["holes"] == []
    assert pair["refactor_shape"]["recommendation"] == ActionKind.CONSOLIDATE_CLONE
    assert pair["refactor_shape"]["shape_kind"] == "statement_sequence_anti_unification_skeleton"
    assert pair["refactor_shape"]["renderable_skeleton"]["lines"][0].startswith(
        "function <H_FUNCTION>"
    )
    assert pair["refactor_shape"]["skeleton_validity"] == "illustrative_only"


@pytest.fixture(scope="module")
def divergent_cluster_pair() -> tuple[dict[str, Any], dict[str, Any]]:
    cluster = cluster_by_shape(
        fixture_cluster_payloads(
            [
                ("divergent/src/json.py", "source"),
                ("divergent/tests/direct.py", "test"),
            ]
        ),
        "fn(Path,str)->None",
    )
    return cluster, relation_pair_by_kind(cluster, RelationKind.COMMON_PREFIX_DIVERGENT_TAIL)


def test_signature_clusters_describe_divergent_tail_classification(
    divergent_cluster_pair: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    cluster, divergent = divergent_cluster_pair
    relation_kinds = {pair["relation_kind"] for pair in cluster["structural_relation_pairs"]}

    assert RelationKind.BODY_IDENTICAL in relation_kinds
    assert RelationKind.COMMON_PREFIX_DIVERGENT_TAIL in relation_kinds
    assert "EXTRA_CONTEXT_MANAGER_DELTA" in divergent["delta_kinds"]
    assert "EXTRA_TERMINAL_CALL_DELTA" in divergent["delta_kinds"]
    assert "RECEIVER_SHAPE_DELTA" in divergent["delta_kinds"]
    assert divergent["clone_family"] == CloneClass.TYPE_3_NEAR_MISS
    assert divergent["clone_type"] == CloneClass.TYPE_3_NEAR_MISS
    assert divergent["recommended_action"] == ActionKind.INSPECT_SHARED_LIFECYCLE
    assert "structural_delta_classification" in divergent["clone_classification"]["basis"]
    assert divergent["refactorability_kind"] == "low"


def test_signature_clusters_score_divergent_tail_costs(
    divergent_cluster_pair: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    _cluster, divergent = divergent_cluster_pair

    assert divergent["abstraction_cost_score"] > MIN_DIVERGENT_ABSTRACTION_COST
    assert_positive_components(
        divergent["abstraction_cost_components"],
        ("cross_module_dependency_cost", "public_api_cost"),
    )
    assert divergent["refactorability_components"]["abstraction_cost_penalty"] < 0
    assert divergent["confidence_score"] <= divergent["relatedness_score"]
    assert_positive_fields(divergent, ("graph_similarity",))
    assert_true_fields(divergent, ("shared_argument_flow_in_tail",))


def test_signature_clusters_describe_divergent_tail_refactor_shape(
    divergent_cluster_pair: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    _cluster, divergent = divergent_cluster_pair

    assert divergent["anti_unification"]["common_prefix_length"] == 1
    assert divergent["anti_unification"]["template"]
    assert divergent["anti_unification"]["hole_bindings"]
    assert divergent["refactor_shape"]["holes"]
    assert divergent["refactor_shape"]["renderable_skeleton"]["suppressed"] is False
    assert divergent["refactor_shape"]["recommendation"] == ActionKind.INSPECT_SHARED_LIFECYCLE
    assert any(
        hole["parameterization"] == "local_helper_or_keep_separate"
        for hole in divergent["refactor_shape"]["holes"]
    )
    assert divergent["anti_unification"]["shared_param_flow_through_holes"] is True


def test_signature_clusters_summarize_divergent_tail_candidate_generation(
    divergent_cluster_pair: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    cluster, _divergent = divergent_cluster_pair

    assert cluster["structural_subclusters"]
    assert_candidate_generation(
        cluster,
        implemented_scope="within_signature_shape_bucket",
        method="bounded_pair_buckets",
        eligible_member_count=EXPECTED_DIVERGENT_CLUSTER_MEMBER_COUNT,
        candidate_pair_count=EXPECTED_DIVERGENT_CLUSTER_MEMBER_COUNT,
    )


def test_signature_clusters_summarize_divergent_tail_refactor_actions(
    divergent_cluster_pair: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    cluster, _divergent = divergent_cluster_pair

    assert cluster["refactor_action_summary"]["primary_action"] == ActionKind.CONSOLIDATE_CLONE
    assert (
        cluster["refactor_action_summary"]["primary_scope"]
        == "consolidate exact or renamed subclusters only"
    )
    assert ActionKind.DO_NOT_REFACTOR in cluster["refactor_action_summary"]["not_recommended"]
    assert any(
        action["kind"] == ActionKind.DO_NOT_REFACTOR
        and action["status"] == "not_recommended"
        and "COMMON_REGION_TOO_SMALL" in action["rejection_reasons"]
        for action in cluster["refactor_action_candidates"]
    )
    assert any(
        action["kind"] == ActionKind.DO_NOT_REFACTOR
        and action["status"] == "not_recommended"
        and "GROUP_TOO_BROAD_FOR_SINGLE_REFACTOR" in action["rejection_reasons"]
        for action in cluster["refactor_action_candidates"]
    )


def test_signature_clusters_compare_line_heavy_payload_builders() -> None:
    cluster = cluster_by_shape(
        fixture_cluster_payloads([("payload_builders.py", "source")]),
        "fn(Json,Json,BudgetConfig | None)->Json",
    )

    assert_candidate_generation(
        cluster,
        method="payload_builder_terminal_call",
        eligible_member_count=EXPECTED_PAYLOAD_BUILDER_MEMBER_COUNT,
        candidate_pair_count=EXPECTED_PAYLOAD_BUILDER_PAIR_COUNT,
    )
    assert cluster["structural_relation_pairs"]


def test_signature_clusters_emit_abstraction_actions_for_stable_wrappers() -> None:
    cluster = cluster_by_shape(
        fixture_cluster_payloads([("stable_wrappers.py", "source")]),
        "fn(list[dict],list[dict])->list[str]",
    )
    pair = relation_pair_by_kind(cluster, RelationKind.COMMON_WRAPPER_DIFFERENT_CORE)

    assert pair["refactorability_score"] >= MIN_WRAPPER_REFACTORABILITY_SCORE
    assert pair["abstraction_cost_score"] < MAX_WRAPPER_ABSTRACTION_COST
    assert pair["refactorability_components"]["local_module_scope"] > 0
    assert pair["confidence_score"] >= MIN_WRAPPER_CONFIDENCE_SCORE
    assert pair["clone_type"] == CloneClass.TYPE_3_NEAR_MISS
    assert pair["recommended_action"] == ActionKind.INTRODUCE_ABSTRACTION
    assert pair["refactor_shape"]["recommendation"] == ActionKind.INTRODUCE_ABSTRACTION
    assert pair["refactor_shape"]["renderable_skeleton"]["suppressed"] is False
    assert any(
        action["kind"] == ActionKind.INTRODUCE_ABSTRACTION
        for action in pair["refactor_action_candidates"]
    )
    assert cluster["refactor_action_summary"]["primary_action"] == ActionKind.INTRODUCE_ABSTRACTION


def test_signature_clusters_capture_argument_normalization_wrappers() -> None:
    cluster = cluster_with_evidence(
        fixture_cluster_payloads([("argument_normalization.py", "source")]),
        EvidenceKind.ARGUMENT_NORMALIZATION_WRAPPER,
    )
    pair = cluster["structural_relation_pairs"][0]
    normalization = pair["relation_basis"]["argument_normalization"]

    assert cluster["canonical_shape"] == (
        "argument_normalization_wrapper(fn(bytes)->str <-> fn(str)->str)"
    )
    assert cluster["candidate_generation"]["implemented_scope"] == (
        "cross_signature_argument_normalization_bucket"
    )
    assert pair["relation_kind"] == RelationKind.ARGUMENT_NORMALIZATION_WRAPPER
    assert pair["recommended_action"] == ActionKind.REUSE_EXISTING_HELPER
    assert pair["relation_basis"]["same_signature_shape"] is False
    assert normalization["wrapper_parameter_type"] == "str"
    assert normalization["primitive_parameter_type"] == "bytes"
    assert normalization["transform_tokens"] == ["ARG0.encode(args=CONST_STR;kwargs=)"]
    assert "ARGUMENT_NORMALIZATION_DELTA" in pair["delta_kinds"]
    assert "typed_argument_normalization_wrapper" in pair["clone_classification"]["basis"]
    assert cluster["refactor_action_summary"]["primary_action"] == (
        ActionKind.REUSE_EXISTING_HELPER
    )


def test_abstraction_estimate_is_honest_without_holes_or_deltas() -> None:
    estimate = abstraction_estimate(
        [],
        0.2,
        delta_kinds=(),
        recommendation=ActionKind.INTRODUCE_ABSTRACTION,
    )

    assert estimate.estimate_basis == "relation_kind_only"
    assert estimate.estimated_parameters == "unknown"
    assert estimate.parameterization_confidence == "low"
    assert estimate.variation_points == "unavailable"


def test_policy_constant_clusters_capture_duplicated_policy_literals() -> None:
    clusters = fixture_payload(
        [
            ("policy_constants.py", "source"),
            ("policy_constants_copy.py", "source"),
        ]
    )
    policy_cluster = clusters["policy_constant_clusters"][0]

    assert policy_cluster["review_relevance"] == "duplicated_policy_constant"
    assert policy_cluster["priority_hint"] == "high"
    assert policy_cluster["members"][0]["symbol"] == "PRIORITY_ORDER"
    assert policy_cluster["evidence_kinds"] == [EvidenceKind.POLICY_CONSTANT_DUPLICATE]


def assert_pair_classification(
    pair: dict[str, Any],
    *,
    relation_kind: RelationKind,
    clone_type: CloneClass,
    action: ActionKind,
    refactorability_kind: str,
) -> None:
    assert pair["relation_kind"] == relation_kind
    assert pair["clone_family"] == clone_type
    assert pair["clone_type"] == clone_type
    assert pair["recommended_action"] == action
    assert pair["refactorability_kind"] == refactorability_kind


def assert_candidate_generation(
    cluster: dict[str, Any],
    *,
    eligible_member_count: int,
    candidate_pair_count: int,
    method: str,
    implemented_scope: str | None = None,
) -> None:
    generation = cluster["candidate_generation"]
    if implemented_scope is not None:
        assert generation["implemented_scope"] == implemented_scope
    assert method in generation["methods"]
    assert generation["eligible_member_count"] == eligible_member_count
    assert generation["candidate_pair_count"] == candidate_pair_count


def assert_positive_components(components: object, names: tuple[str, ...]) -> None:
    assert isinstance(components, dict)
    for name in names:
        assert components[name] > 0


def assert_positive_fields(payload: dict[str, Any], names: tuple[str, ...]) -> None:
    for name in names:
        assert payload[name] > 0


def assert_true_fields(payload: dict[str, Any], names: tuple[str, ...]) -> None:
    for name in names:
        assert payload[name] is True
