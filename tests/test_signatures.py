from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from helpers import file_record as _file_record
from pytest import MonkeyPatch

from codeseam.adapters.languages.python.adapter import PythonAstAdapter
from codeseam.analysis import (
    AbstractionKind,
    ActionKind,
    AdapterId,
    CalleeShape,
    CallFingerprint,
    CloneClass,
    Cluster,
    Clusters,
    DataflowGraph,
    DataflowNode,
    EvidenceKind,
    ExpressionShape,
    FunctionIR,
    LanguageFamily,
    OrderedTree,
    ParamIR,
    RelationKind,
    RepositoryFacts,
    RepositoryScan,
    SignatureBodySummary,
    SignatureCore,
    SignatureIdentity,
    SignatureRecord,
    SignatureShape,
    SignatureTypeSource,
    abstraction_estimate,
    adapter_id,
    build_clusters,
    build_repository_facts,
    canonical_shape,
    language_family,
    member_features,
    signature_analysis_from_record,
    signature_core_from_record,
    signature_shape,
)
from codeseam.cache import (
    RELATION_DETAIL_FEATURE_CACHE_NAMESPACE,
    AnalysisCacheContext,
    LanguageRunCache,
    PersistentCache,
    persistent_cache,
)
from codeseam.config import Config, load_config
from codeseam.output.serializers.signatures import (
    signature_clusters_payload,
    signature_record_payload,
)
from codeseam.pipeline.signatures import SignatureArtifacts, build_signature_artifacts
from codeseam.platform import as_json_object, json_int

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "signatures"
MIN_EXACT_RELATEDNESS_SCORE = 0.9
MIN_EXACT_REFACTORABILITY_SCORE = 0.5
MIN_WRAPPER_CONFIDENCE_SCORE = 0.7
MIN_WRAPPER_REFACTORABILITY_SCORE = 0.6
MAX_EXACT_ABSTRACTION_COST = 0.1
MIN_DIVERGENT_ABSTRACTION_COST = 0.4
MAX_WRAPPER_ABSTRACTION_COST = 0.4
EXPECTED_DEBUG_TREE_NODE_COUNT = 2


def test_member_features_use_typed_signature_core() -> None:
    signature = _signature("sig_none", "python", "src/a.py", "", "fn()->T", "shape")

    assert member_features(signature).body_hash == ""


def test_signature_record_serializes_without_generic_dataclass_walk() -> None:
    record = _signature("sig_1", "Python", "src/a.py", "fn", "fn()->T", "h")
    record = replace(
        record,
        function_id="fn_1",
        body_tree_node_count=EXPECTED_DEBUG_TREE_NODE_COUNT,
    )

    payload = signature_record_payload(record)

    assert payload["schema_version"] == "codeseam.signature.v1"
    assert payload["signature_id"] == "sig_1"
    assert payload["function_id"] == "fn_1"
    assert payload["language_family"] == "python"
    assert payload["body_tree"] is None
    assert payload["body_tree_node_count"] == EXPECTED_DEBUG_TREE_NODE_COUNT
    assert payload["graph_features"] == []


def test_signature_record_coerces_boundary_enums() -> None:
    record = SignatureRecord(
        schema_version="codeseam.signature.v1",
        signature_id="sig_1",
        function_id=None,
        language="Python",
        language_family=cast(Any, "python"),
        adapter=cast(Any, "python_ast"),
        file="src/a.py",
        symbol="fn",
        normalized_symbol="fn",
        container=None,
        start_line=1,
        end_line=1,
        role="source",
        type_source=cast(Any, "declared_syntax"),
        parameters=[],
        return_type="UNKNOWN",
        raw_signature="",
        canonical_shape="fn()->UNKNOWN",
        shape_hash="shape",
        body_line_count=1,
        body_shape="",
        body_shape_hash="",
        body_tree=None,
        body_tree_node_count=0,
    )

    assert record.language_family is LanguageFamily.PYTHON
    assert record.adapter is AdapterId.PYTHON_AST
    assert record.type_source is SignatureTypeSource.DECLARED_SYNTAX


def test_signature_core_exposes_typed_lifecycle_views() -> None:
    core = SignatureCore(
        language="python",
        language_family=LanguageFamily.PYTHON,
        adapter=AdapterId.PYTHON_AST,
        file="src/a.py",
        symbol="fn",
        normalized_symbol="fn",
        container=None,
        start_line=1,
        end_line=2,
        role="source",
        type_source=SignatureTypeSource.DECLARED_SYNTAX,
        parameters=("str",),
        return_type="str",
        canonical_shape="fn(str)->str",
        shape_hash="shape",
        body_line_count=1,
        body_shape_hash="body",
        body_tree_node_count=2,
        statement_sequence=("RETURN:ARG0",),
        call_tokens=("str.strip",),
        return_signature=("RETURN:ARG0",),
        signature_id="sig_1",
        function_id="fn_1",
        semantic_roles=("api_surface",),
    )

    assert core.identity == SignatureIdentity(
        language="python",
        language_family=LanguageFamily.PYTHON,
        adapter=AdapterId.PYTHON_AST,
        file="src/a.py",
        symbol="fn",
        normalized_symbol="fn",
        container=None,
        start_line=1,
        end_line=2,
        role="source",
        signature_id="sig_1",
        function_id="fn_1",
    )
    assert core.shape == SignatureShape(
        type_source=SignatureTypeSource.DECLARED_SYNTAX,
        parameters=("str",),
        return_type="str",
        canonical_shape="fn(str)->str",
        shape_hash="shape",
    )
    assert core.body == SignatureBodySummary(
        body_line_count=1,
        body_shape_hash="body",
        body_tree_node_count=2,
        statement_sequence=("RETURN:ARG0",),
        call_tokens=("str.strip",),
        return_signature=("RETURN:ARG0",),
    )
    assert core.semantic_roles == ("api_surface",)


def test_signature_analysis_from_record_accepts_constant_kwargs() -> None:
    record = _signature_record("sig_1", "python", "src/a.py", "decode_arg", "fn()->T", "h")
    token = "ARG0.decode(args=;kwargs=encoding:CONST_utf8)"
    record.call_fingerprints = (
        CallFingerprint(
            kind="CALL",
            token=token,
            callee_shape=CalleeShape(name_tokens=("decode",), call_kind="method"),
            receiver_shape=ExpressionShape(base="ARG0"),
            kwarg_shape=(("encoding", "CONST_utf8"),),
        ),
    )

    analysis = signature_analysis_from_record(record)

    assert analysis.features.normalization_transform_tokens == frozenset((token,))


def test_signature_analysis_from_record_rejects_non_constant_transform_args() -> None:
    record = _signature_record("sig_1", "python", "src/a.py", "decode_arg", "fn()->T", "h")
    record.call_fingerprints = (
        CallFingerprint(
            kind="CALL",
            token="ARG0.decode(args=ARG1;kwargs=)",
            callee_shape=CalleeShape(name_tokens=("decode",), call_kind="method"),
            receiver_shape=ExpressionShape(base="ARG0"),
            arg_roles=("ARG1",),
        ),
    )

    analysis = signature_analysis_from_record(record)

    assert analysis.features.normalization_transform_tokens == frozenset()


def test_statement_arg_reads_ignore_malformed_statement_ids() -> None:
    record = _signature_record("sig_1", "python", "src/a.py", "read_arg", "fn()->T", "h")
    record.local_dataflow_graph = DataflowGraph(
        nodes=(
            DataflowNode(id="STMTx", label="bad", kind="statement", arg_reads=("ARG0",)),
            DataflowNode(id="STMT2", label="good", kind="statement", arg_reads=("ARG1",)),
        )
    )

    analysis = signature_analysis_from_record(record)

    assert analysis.features.statement_arg_reads == ((2, ("ARG1",)),)


def test_signature_record_can_emit_debug_body_tree_on_demand() -> None:
    record = _signature_record("sig_1", "Python", "src/a.py", "fn", "fn()->T", "h")
    record.body_tree = OrderedTree("Module", (OrderedTree("Return"),))

    payload = signature_record_payload(
        signature_core_from_record(record),
        body_tree=record.body_tree,
    )

    assert payload["body_tree"] == {
        "label": "Module",
        "children": [{"label": "Return", "children": []}],
    }


EXPECTED_DIVERGENT_CLUSTER_MEMBER_COUNT = 3
EXPECTED_PAYLOAD_BUILDER_MEMBER_COUNT = 2
EXPECTED_PAYLOAD_BUILDER_PAIR_COUNT = 1
BROAD_UNKNOWN_MEMBER_COUNT = 501
EXPECTED_TYPESCRIPT_TEST_MEMBER_COUNT = 30
EXPECTED_BROAD_TEST_MEMBER_COUNT = 40
EXPECTED_BROAD_SOURCE_MEMBER_COUNT = 5
EXPECTED_LOCAL_DUPLICATE_OCCURRENCES = 2


@pytest.mark.parametrize(
    ("parameters", "return_type", "expected"),
    [
        (["T"], "T", "fn(G0)->G0"),
        (["U"], "U", "fn(G0)->G0"),
        (["T"], "U", "fn(G0)->G1"),
    ],
)
def test_canonical_shape_normalizes_generic_relationships(
    parameters: list[str],
    return_type: str,
    expected: str,
) -> None:
    assert canonical_shape(parameters, return_type)[0] == expected


def test_signature_shape_can_be_derived_from_function_ir() -> None:
    shape = signature_shape(
        FunctionIR(
            language="typescript",
            language_family=LanguageFamily.ECMASCRIPT_TYPESCRIPT,
            file="src/app.ts",
            name="identity",
            container=None,
            kind="function",
            start_line=1,
            end_line=1,
            is_async=False,
            is_exported_or_public=True,
            params=(ParamIR("T"),),
            return_annotation="T",
            declared_generics=("T",),
            raw_signature="function identity<T>(value: T): T",
            source_text="",
            body_text="",
            body_line_count=1,
            branch_count=0,
            loop_count=0,
            return_count=0,
            max_nesting=0,
            adapter=AdapterId.TREESITTER_ECMASCRIPT_TYPESCRIPT,
            extraction_confidence="high",
            caveats=(),
        )
    )

    assert shape.canonical_shape == "fn(G0)->G0"
    assert shape.type_source is SignatureTypeSource.DECLARED_SYNTAX
    assert shape.caveats == []


def test_signature_clusters_add_scope_aware_analogous_observations() -> None:
    shape, shape_hash = canonical_shape(["UNKNOWN"], "UNKNOWN")
    clusters = _cluster_payloads(
        build_clusters(
            [
                _signature("sigrec_000001", "python", "src/a.py", "load", shape, shape_hash),
                _signature("sigrec_000002", "python", "src/b.py", "parse", shape, shape_hash),
                _signature(
                    "sigrec_000003",
                    "typescript",
                    "src/c.ts",
                    "load",
                    shape,
                    shape_hash,
                    family="ecmascript_typescript",
                    adapter="treesitter_ecmascript_typescript",
                ),
            ]
        )
    )

    same_language = clusters[0]
    analogous = clusters[1]

    assert same_language["cluster_id"] == "sigcl_000001"
    assert same_language["cluster_scope"] == "same_language"
    assert same_language["language"] == "python"
    assert analogous["cluster_id"] == "sigcl_000002"
    assert analogous["cluster_scope"] == "cross_language"
    assert analogous["language"] == "multiple"
    assert analogous["review_relevance"] == "cross_language_signature_shape_observation"
    assert analogous["languages"] == ["python", "typescript"]
    assert analogous["adapters"] == ["python_ast", "treesitter_ecmascript_typescript"]


def test_signature_clusters_classify_js_ts_as_same_family() -> None:
    shape, shape_hash = canonical_shape(["UNKNOWN"], "UNKNOWN")
    clusters = _cluster_payloads(
        build_clusters(
            [
                _signature(
                    "sigrec_000001",
                    "javascript",
                    "src/a.js",
                    "load",
                    shape,
                    shape_hash,
                    family="ecmascript_typescript",
                    adapter="treesitter_ecmascript_typescript",
                ),
                _signature(
                    "sigrec_000002",
                    "typescript",
                    "src/b.ts",
                    "load",
                    shape,
                    shape_hash,
                    family="ecmascript_typescript",
                    adapter="treesitter_ecmascript_typescript",
                ),
            ]
        )
    )

    assert len(clusters) == 1
    assert clusters[0]["cluster_scope"] == "same_family"
    assert clusters[0]["review_relevance"] == "same_family_signature_shape_observation"


def test_broad_unknown_signature_clusters_degrade_to_summary_only() -> None:
    shape, shape_hash = canonical_shape(["UNKNOWN"], "UNKNOWN")
    clusters = build_clusters(
        [
            _signature(
                f"sigrec_{index:06d}",
                "python",
                f"src/mod_{index}.py",
                f"load_{index}",
                shape,
                shape_hash,
            )
            for index in range(BROAD_UNKNOWN_MEMBER_COUNT)
        ]
    )

    assert len(clusters) == 1
    cluster = clusters[0]
    assert cluster.member_count == BROAD_UNKNOWN_MEMBER_COUNT
    assert cluster.cluster_scope == "broad_unknown_signature_summary"
    assert cluster.review_relevance == "weak_unknown_signature_recurrence"
    assert cluster.enrichment is None
    assert any(
        claim.startswith("Broad UNKNOWN signature recurrence is weak evidence")
        for claim in cluster.non_claims
    )


def test_broad_unknown_signature_clusters_preserve_exact_body_duplicates() -> None:
    shape, shape_hash = canonical_shape(["UNKNOWN"], "UNKNOWN")
    duplicates = [
        _signature_with_body_hash(
            "sigrec_exact_001",
            "src/a.py",
            "load_a",
            shape,
            shape_hash,
            "shape32:exact",
        ),
        _signature_with_body_hash(
            "sigrec_exact_002",
            "tests/b.py",
            "load_b",
            shape,
            shape_hash,
            "shape32:exact",
        ),
    ]
    noise = [
        _signature(
            f"sigrec_noise_{index:06d}",
            "python",
            f"pkg_{index}/mod.py",
            f"load_{index}",
            shape,
            shape_hash,
        )
        for index in range(BROAD_UNKNOWN_MEMBER_COUNT - len(duplicates))
    ]

    clusters = build_clusters([*duplicates, *noise])
    exact_clusters = [
        cluster
        for cluster in clusters
        if cluster.cluster_scope == "broad_unknown_signature_exact_body"
    ]
    summary_clusters = [
        cluster
        for cluster in clusters
        if cluster.cluster_scope == "broad_unknown_signature_summary"
    ]

    assert len(exact_clusters) == 1
    assert len(summary_clusters) == 1
    assert exact_clusters[0].member_count == len(duplicates)
    assert exact_clusters[0].enrichment is not None
    assert (
        exact_clusters[0].enrichment.candidate_generation.implemented_scope
        == "exact_body_hash_before_broad_unknown_degradation"
    )
    assert summary_clusters[0].member_count == len(noise)
    assert summary_clusters[0].enrichment is None


def test_broad_signature_clusters_split_test_and_source_members() -> None:
    shape, shape_hash = canonical_shape([], "None")
    test_members = [
        _signature(
            f"sigrec_test_{index:06d}",
            "python",
            f"tests/test_mod_{index}.py",
            f"test_case_{index}",
            shape,
            shape_hash,
            role="test",
        )
        for index in range(40)
    ]
    source_members = [
        _signature(
            f"sigrec_source_{index:06d}",
            "python",
            f"src/mod_{index}.py",
            f"configure_{index}",
            shape,
            shape_hash,
        )
        for index in range(5)
    ]

    clusters = build_clusters([*test_members, *source_members])

    assert {cluster.cluster_scope for cluster in clusters} == {
        "broad_test_signature_summary",
        "same_language",
    }
    assert all(
        len({member.signature.role for member in cluster.members}) == 1 for cluster in clusters
    )
    test_cluster = next(
        cluster for cluster in clusters if cluster.cluster_scope == "broad_test_signature_summary"
    )
    assert test_cluster.enrichment is None
    assert test_cluster.review_relevance == "test_pattern_family"


def test_broad_test_clusters_do_not_depend_on_python_or_pytest_shapes() -> None:
    shape, shape_hash = canonical_shape(["RequestContext"], "Promise<Result>")
    test_members = [
        _signature(
            f"sigrec_js_test_{index:06d}",
            "TypeScript",
            f"tests/service_{index}.spec.ts",
            f"handles_case_{index}",
            shape,
            shape_hash,
            family="ecmascript_typescript",
            adapter="treesitter_typescript",
            role="test",
        )
        for index in range(30)
    ]

    clusters = build_clusters(test_members)

    assert len(clusters) == 1
    assert clusters[0].cluster_scope == "broad_test_signature_summary"
    assert clusters[0].enrichment is None
    assert clusters[0].review_relevance == "test_pattern_family"


def test_python_signature_clusters_record_small_structural_duplicates() -> None:
    clusters = _fixture_cluster_payloads([("small_structural_duplicate.py", "source")])
    cluster = next(
        item for item in clusters if EvidenceKind.STRUCTURAL_DUPLICATE in item["evidence_kinds"]
    )
    pair = cluster["structural_duplicate_pairs"][0]

    assert cluster["enrichment_schema_version"] == "codeseam.signature_cluster_enrichment.v1"
    assert cluster["cluster_confidence"] == cluster["confidence"]
    assert cluster["abstraction_kind"] == AbstractionKind.EXTRACT_HELPER
    assert pair["name_similarity"] == 1.0
    assert pair["tree_similarity"] == 1.0
    assert pair["tree_distance"] == 0.0
    assert pair["tree_edit_distance"] == 0
    assert pair["tree_node_count"] > 0
    assert pair["tree_distance_source"] == "body_hash"
    assert pair["schema_version"] == "codeseam.structural_relation_pair.v1"
    assert pair["score_model"] == "heuristic_v1"
    assert pair["score_interpretation"] == "ranking_signal_not_probability"
    assert pair["pair_confidence"] == pair["confidence_score"]
    assert pair["relation_basis"]["body_hash_match"] is True
    assert pair["relation_kind"] == RelationKind.BODY_IDENTICAL
    assert pair["relatedness_score"] > MIN_EXACT_RELATEDNESS_SCORE
    assert pair["refactorability_score"] > MIN_EXACT_REFACTORABILITY_SCORE
    assert pair["abstraction_cost_score"] <= MAX_EXACT_ABSTRACTION_COST
    assert pair["abstraction_cost_components"]["hole_count"] == 0.0
    assert pair["refactorability_components"]["same_source_role"] > 0
    assert pair["confidence_score"] > MIN_EXACT_RELATEDNESS_SCORE
    assert pair["clone_family"] == CloneClass.TYPE_1_EXACT
    assert pair["clone_type"] == CloneClass.TYPE_1_EXACT
    assert pair["recommended_action"] == ActionKind.CONSOLIDATE_CLONE
    assert pair["clone_classification"]["basis"]
    assert pair["refactorability_kind"] == "high"
    assert pair["graph_similarity"] == 1.0
    assert pair["risk_score"] >= 0
    assert pair["anti_unification"]["stable_node_ratio"] == 1.0
    assert pair["refactor_shape"]["abstraction_domain"] == "normalized_statement_sequence"
    assert pair["refactor_shape"]["renderable_skeleton"]["suppressed"] is False
    assert pair["refactor_shape"]["holes"] == []
    assert pair["refactor_shape"]["recommendation"] == ActionKind.CONSOLIDATE_CLONE
    assert pair["refactor_shape"]["shape_kind"] == "statement_sequence_anti_unification_skeleton"
    assert pair["refactor_shape"]["abstraction_domain"] == "normalized_statement_sequence"
    assert pair["refactor_shape"]["renderable_skeleton"]["lines"][0].startswith(
        "function <H_FUNCTION>"
    )
    assert pair["refactor_shape"]["skeleton_validity"] == "illustrative_only"
    assert pair["same_role"] is True


def test_signature_artifacts_skip_python_ast_parse_on_warm_cache(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    path_roles = [("warm_cache_service.py", "source")]
    cache_root = tmp_path / ".cache" / "codeseam"

    first_cache = persistent_cache(cache_root, enabled=True)
    try:
        first = _fixture_artifacts(path_roles, _audit_cache(first_cache))
    finally:
        first_cache.close()
    assert [record.core.symbol for record in first.records] == ["repeated"]

    def fail_parse(path: Path) -> object:
        raise AssertionError(f"unexpected Python AST parse for unchanged file: {path}")

    monkeypatch.setattr("codeseam.adapters.languages.python.adapter.parse_python", fail_parse)
    monkeypatch.setattr("codeseam.adapters.languages.python.signatures.parse_python", fail_parse)

    second_cache = persistent_cache(cache_root, enabled=True)
    try:
        second = _fixture_artifacts(path_roles, _audit_cache(second_cache))
        stats = second_cache.run_stats()
    finally:
        second_cache.close()

    namespaces = as_json_object(stats.get("namespaces"))

    assert [record.core.symbol for record in second.records] == ["repeated"]
    assert as_json_object(namespaces.get("signature_cores"))["hits"] == 1
    assert as_json_object(namespaces.get("signature_features"))["hits"] == 1
    assert as_json_object(namespaces.get("signature_output"))["hits"] == 1
    assert as_json_object(namespaces.get("policy_constants"))["hits"] == 1


def test_relation_detail_cache_avoids_warm_hydration(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    path_roles = [("small_structural_duplicate.py", "source")]
    cache_root = tmp_path / ".cache" / "codeseam"

    first_cache = persistent_cache(cache_root, enabled=True)
    try:
        _fixture_artifacts(path_roles, _audit_cache(first_cache))
    finally:
        first_cache.close()

    def fail_hydration(self: PythonAstAdapter, request: object) -> object:
        raise AssertionError("warm relation-detail cache should bypass adapter hydration")

    original_get_blob_object = PersistentCache.get_blob_object
    original_get_blobs = PersistentCache.get_blobs
    batch_reads: list[tuple[str, ...]] = []

    def reject_relation_detail_item_read(
        self: PersistentCache,
        namespace: str,
        key: str,
    ) -> object | None:
        if namespace == RELATION_DETAIL_FEATURE_CACHE_NAMESPACE:
            raise AssertionError("relation-detail cache should use batched reads")
        return original_get_blob_object(self, namespace, key)

    def capture_relation_detail_batch_read(
        self: PersistentCache,
        namespace: str,
        keys: list[str] | tuple[str, ...],
    ) -> dict[str, bytes]:
        if namespace == RELATION_DETAIL_FEATURE_CACHE_NAMESPACE:
            batch_reads.append(tuple(keys))
        return original_get_blobs(self, namespace, keys)

    monkeypatch.setattr(PythonAstAdapter, "hydrate_relation_detail", fail_hydration)
    monkeypatch.setattr(PersistentCache, "get_blob_object", reject_relation_detail_item_read)
    monkeypatch.setattr(PersistentCache, "get_blobs", capture_relation_detail_batch_read)

    second_cache = persistent_cache(cache_root, enabled=True)
    try:
        _fixture_artifacts(path_roles, _audit_cache(second_cache))
        stats = second_cache.run_stats()
    finally:
        second_cache.close()

    namespaces = as_json_object(stats.get("namespaces"))
    relation_detail_stats = as_json_object(namespaces.get("relation_detail_features"))
    assert batch_reads
    assert all(len(keys) > 1 for keys in batch_reads)
    assert json_int(relation_detail_stats.get("hits")) > 0
    assert json_int(relation_detail_stats.get("misses")) == 0


@pytest.mark.parametrize(
    ("fixture", "language", "symbol"),
    [
        ("intra_function_duplicate.py", "Python", "completed_result"),
        ("intra_function_duplicate.ts", "TypeScript", "completedResult"),
    ],
)
def test_intra_function_duplicate_blocks_are_collected(
    fixture: str,
    language: str,
    symbol: str,
) -> None:
    facts = build_repository_facts(
        RepositoryScan(
            records=[_file_record(fixture, language=language)],
            selected_paths=[fixture],
        )
    )
    artifacts = build_signature_artifacts(load_config(FIXTURE_ROOT), facts, [])
    signature = next(item for item in artifacts.records if item.core.symbol == symbol)

    blocks = signature.core.intra_function_duplicate_blocks

    assert len(blocks) == 1
    assert len(blocks[0].occurrences) == EXPECTED_LOCAL_DUPLICATE_OCCURRENCES


def test_signature_clusters_describe_divergent_tail_relations() -> None:
    clusters = _fixture_cluster_payloads(
        [
            ("divergent/src/json.py", "source"),
            ("divergent/tests/direct.py", "test"),
        ]
    )
    cluster = next(item for item in clusters if item["canonical_shape"] == "fn(Path,str)->None")
    relation_kinds = {pair["relation_kind"] for pair in cluster["structural_relation_pairs"]}

    assert RelationKind.BODY_IDENTICAL in relation_kinds
    assert RelationKind.COMMON_PREFIX_DIVERGENT_TAIL in relation_kinds
    divergent = next(
        pair
        for pair in cluster["structural_relation_pairs"]
        if pair["relation_kind"] == RelationKind.COMMON_PREFIX_DIVERGENT_TAIL
    )
    assert "EXTRA_CONTEXT_MANAGER_DELTA" in divergent["delta_kinds"]
    assert "EXTRA_TERMINAL_CALL_DELTA" in divergent["delta_kinds"]
    assert "RECEIVER_SHAPE_DELTA" in divergent["delta_kinds"]
    assert divergent["clone_family"] == CloneClass.TYPE_3_NEAR_MISS
    assert divergent["clone_type"] == CloneClass.TYPE_3_NEAR_MISS
    assert divergent["recommended_action"] == ActionKind.INSPECT_SHARED_LIFECYCLE
    assert "structural_delta_classification" in divergent["clone_classification"]["basis"]
    assert divergent["refactorability_kind"] == "low"
    assert divergent["abstraction_cost_score"] > MIN_DIVERGENT_ABSTRACTION_COST
    assert divergent["abstraction_cost_components"]["cross_module_dependency_cost"] > 0
    assert divergent["abstraction_cost_components"]["public_api_cost"] > 0
    assert divergent["refactorability_components"]["abstraction_cost_penalty"] < 0
    assert divergent["confidence_score"] <= divergent["relatedness_score"]
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
    assert divergent["shared_argument_flow_in_tail"] is True
    assert divergent["graph_similarity"] > 0
    assert cluster["structural_subclusters"]
    assert cluster["candidate_generation"]["implemented_scope"] == "within_signature_shape_bucket"
    assert "bounded_pair_buckets" in cluster["candidate_generation"]["methods"]
    assert (
        cluster["candidate_generation"]["eligible_member_count"]
        == EXPECTED_DIVERGENT_CLUSTER_MEMBER_COUNT
    )
    assert (
        cluster["candidate_generation"]["candidate_pair_count"]
        == EXPECTED_DIVERGENT_CLUSTER_MEMBER_COUNT
    )
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
    clusters = _fixture_cluster_payloads([("payload_builders.py", "source")])
    cluster = next(
        item
        for item in clusters
        if item["canonical_shape"] == "fn(Json,Json,BudgetConfig | None)->Json"
    )

    assert (
        cluster["candidate_generation"]["eligible_member_count"]
        == EXPECTED_PAYLOAD_BUILDER_MEMBER_COUNT
    )
    assert (
        cluster["candidate_generation"]["candidate_pair_count"]
        == EXPECTED_PAYLOAD_BUILDER_PAIR_COUNT
    )
    assert "payload_builder_terminal_call" in cluster["candidate_generation"]["methods"]
    assert cluster["structural_relation_pairs"]


def test_signature_clusters_emit_abstraction_actions_for_stable_wrappers() -> None:
    clusters = _fixture_cluster_payloads([("stable_wrappers.py", "source")])
    cluster = next(
        item
        for item in clusters
        if item["canonical_shape"] == "fn(list[dict],list[dict])->list[str]"
    )
    pair = next(
        pair
        for pair in cluster["structural_relation_pairs"]
        if pair["relation_kind"] == RelationKind.COMMON_WRAPPER_DIFFERENT_CORE
    )

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
    clusters = _fixture_cluster_payloads([("argument_normalization.py", "source")])
    cluster = next(
        item
        for item in clusters
        if EvidenceKind.ARGUMENT_NORMALIZATION_WRAPPER in item["evidence_kinds"]
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
    clusters = _fixture_payload(
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


def _cluster_payloads(clusters: tuple[Cluster, ...]) -> list[dict[str, Any]]:
    return cast(
        list[dict[str, Any]],
        signature_clusters_payload(
            Clusters(
                clusters=tuple(clusters),
                policy_constant_clusters=(),
            )
        )["clusters"],
    )


def _signature_artifact_payload(artifacts: SignatureArtifacts) -> dict[str, Any]:
    return signature_clusters_payload(artifacts.clusters)


def _fixture_cluster_payloads(path_roles: list[tuple[str, str]]) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], _fixture_payload(path_roles)["clusters"])


def _fixture_payload(path_roles: list[tuple[str, str]]) -> dict[str, Any]:
    return _signature_artifact_payload(_fixture_artifacts(path_roles))


def _fixture_artifacts(
    path_roles: list[tuple[str, str]],
    cache: AnalysisCacheContext | None = None,
) -> SignatureArtifacts:
    return _signature_artifacts(load_config(FIXTURE_ROOT), path_roles, cache)


def _repository_facts(path_roles: list[tuple[str, str]]) -> RepositoryFacts:
    return build_repository_facts(
        RepositoryScan(
            records=[_file_record(path, role=role) for path, role in path_roles],
            selected_paths=[path for path, _role in path_roles],
        )
    )


def _signature_artifacts(
    config: Config,
    path_roles: list[tuple[str, str]],
    cache: AnalysisCacheContext | None = None,
) -> SignatureArtifacts:
    return build_signature_artifacts(config, _repository_facts(path_roles), [], cache)


def _audit_cache(cache: PersistentCache) -> AnalysisCacheContext:
    return AnalysisCacheContext(
        persistent=cache,
        file_analysis_enabled=True,
        relation_pair_enabled=True,
        language=LanguageRunCache(),
    )


def _signature(  # noqa: PLR0913
    signature_id: str,
    language: str,
    file_path: str,
    symbol: str,
    shape: str,
    shape_hash: str,
    *,
    family: str | None = None,
    adapter: str | None = None,
    role: str = "source",
) -> SignatureCore:
    return signature_core_from_record(
        _signature_record(
            signature_id,
            language,
            file_path,
            symbol,
            shape,
            shape_hash,
            family=family,
            adapter=adapter,
            role=role,
        )
    )


def _signature_with_body_hash(  # noqa: PLR0913
    signature_id: str,
    file_path: str,
    symbol: str,
    shape: str,
    shape_hash: str,
    body_shape_hash: str,
) -> SignatureCore:
    signature = _signature(signature_id, "python", file_path, symbol, shape, shape_hash)
    return replace(signature, body_shape_hash=body_shape_hash)


def _signature_record(  # noqa: PLR0913
    signature_id: str,
    language: str,
    file_path: str,
    symbol: str,
    shape: str,
    shape_hash: str,
    *,
    family: str | None = None,
    adapter: str | None = None,
    role: str = "source",
) -> SignatureRecord:
    return SignatureRecord(
        schema_version="codeseam.signature.v1",
        signature_id=signature_id,
        function_id=None,
        language=language,
        language_family=language_family(family or language),
        adapter=adapter_id(adapter or ("python_ast" if language == "python" else "unknown")),
        file=file_path,
        symbol=symbol,
        normalized_symbol=symbol,
        container=None,
        start_line=1,
        end_line=1,
        role=role,
        type_source=SignatureTypeSource.FALLBACK,
        parameters=["UNKNOWN"],
        return_type="UNKNOWN",
        raw_signature="",
        canonical_shape=shape,
        shape_hash=shape_hash,
        body_line_count=1,
        body_shape="",
        body_shape_hash="",
        body_tree=None,
        body_tree_node_count=0,
        statement_sequence=[],
        call_fingerprints=(),
        parameter_use_vectors={},
        parameter_default_roles={},
        local_dataflow_graph=DataflowGraph(),
        control_context_vector=[],
        caveats=[],
        non_claims=["Same signature shape does not imply same behavior."],
    )
