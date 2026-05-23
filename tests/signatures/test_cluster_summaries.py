from __future__ import annotations

from codeseam.analysis import build_clusters, canonical_shape

from .factories import cluster_payloads, signature, signature_with_body_hash

BROAD_UNKNOWN_MEMBER_COUNT = 501
EXPECTED_TYPESCRIPT_TEST_MEMBER_COUNT = 30
EXPECTED_BROAD_TEST_MEMBER_COUNT = 40
EXPECTED_BROAD_SOURCE_MEMBER_COUNT = 5


def test_signature_clusters_add_scope_aware_analogous_observations() -> None:
    shape, shape_hash = canonical_shape(["UNKNOWN"], "UNKNOWN")
    clusters = cluster_payloads(
        build_clusters(
            [
                signature("sigrec_000001", "python", "src/a.py", "load", shape, shape_hash),
                signature("sigrec_000002", "python", "src/b.py", "parse", shape, shape_hash),
                signature(
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
    clusters = cluster_payloads(
        build_clusters(
            [
                signature(
                    "sigrec_000001",
                    "javascript",
                    "src/a.js",
                    "load",
                    shape,
                    shape_hash,
                    family="ecmascript_typescript",
                    adapter="treesitter_ecmascript_typescript",
                ),
                signature(
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
            signature(
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
        signature_with_body_hash(
            "sigrec_exact_001",
            "src/a.py",
            "load_a",
            shape,
            shape_hash,
            "shape32:exact",
        ),
        signature_with_body_hash(
            "sigrec_exact_002",
            "tests/b.py",
            "load_b",
            shape,
            shape_hash,
            "shape32:exact",
        ),
    ]
    noise = [
        signature(
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
        signature(
            f"sigrec_test_{index:06d}",
            "python",
            f"tests/test_mod_{index}.py",
            f"test_case_{index}",
            shape,
            shape_hash,
            role="test",
        )
        for index in range(EXPECTED_BROAD_TEST_MEMBER_COUNT)
    ]
    source_members = [
        signature(
            f"sigrec_source_{index:06d}",
            "python",
            f"src/mod_{index}.py",
            f"configure_{index}",
            shape,
            shape_hash,
        )
        for index in range(EXPECTED_BROAD_SOURCE_MEMBER_COUNT)
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
        signature(
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
        for index in range(EXPECTED_TYPESCRIPT_TEST_MEMBER_COUNT)
    ]

    clusters = build_clusters(test_members)

    assert len(clusters) == 1
    assert clusters[0].cluster_scope == "broad_test_signature_summary"
    assert clusters[0].enrichment is None
    assert clusters[0].review_relevance == "test_pattern_family"
