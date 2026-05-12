from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from codeseam.adapters.languages import LanguageAnalysisContext, default_language_registry
from codeseam.analysis import (
    ActionKind,
    ActionStatus,
    AdapterId,
    BoundarySpecificity,
    FindingVisibility,
    LanguageFamily,
    MemberFeatureCache,
    RelationKind,
    RelationMemberContext,
    RelationPair,
    ReviewTier,
    SignatureCore,
    SignatureTypeClass,
    SignatureTypeSource,
    classify_contexts,
    classify_signature_type,
    collection_element_type_class,
    is_test_member,
    layer_path,
    pair_actions,
    pairs,
    signature_core_from_record,
)

FIXTURES = Path(__file__).parent / "fixtures" / "low_info_noise"


@dataclass(frozen=True, slots=True)
class FixtureContextExpectation:
    fixtures: tuple[str, ...]
    language: str
    symbols: tuple[str, ...]
    expected_kind: str
    expected_visibility: FindingVisibility
    expected_review_tier: ReviewTier
    expected_summary_eligible: bool
    expected_action: ActionKind
    relation_kind: RelationKind | None = None
    required_tags: tuple[str, ...] = ()


@pytest.mark.parametrize(
    ("type_name", "expected"),
    [
        ("list[str]", SignatureTypeClass.COLLECTION),
        ("Array<string>", SignatureTypeClass.COLLECTION),
        ("Vec<String>", SignatureTypeClass.COLLECTION),
        ("[String]", SignatureTypeClass.COLLECTION),
        ("string[]", SignatureTypeClass.COLLECTION),
        ("dict[str, object]", SignatureTypeClass.MAPPING),
        ("Record<string, unknown>", SignatureTypeClass.MAPPING),
        ("[String: Any]", SignatureTypeClass.MAPPING),
        ("HashMap<String, serde_json::Value>", SignatureTypeClass.MAPPING),
        ("serde_json::Value", SignatureTypeClass.OPAQUE),
    ],
)
def test_type_classifier_normalizes_language_specific_type_spellings(
    type_name: str,
    expected: SignatureTypeClass,
) -> None:
    assert classify_signature_type(type_name) is expected


def test_collection_element_classifier_normalizes_language_specific_spellings() -> None:
    assert collection_element_type_class("Array<FindingDraft>") is SignatureTypeClass.DOMAIN


@pytest.mark.parametrize(
    ("language", "file", "role", "expected"),
    [
        ("Python", "src/conftest.py", "test", True),
        ("TypeScript", "src/user.spec.ts", "", True),
        ("JavaScript", "src/payment-test.js", "test", True),
        ("TypeScript", "tests/helpers/setup.ts", "", True),
        ("Python", "src/app.py", "", False),
    ],
)
def test_relation_test_member_detection_uses_repository_role_and_common_path_facts(
    language: str,
    file: str,
    role: str,
    expected: bool,
) -> None:
    assert is_test_member(_relation_member(language, file, role=role)) is expected


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("src/codeseam/analysis/relations/risks.py", "codeseam/analysis"),
        ("lib/codeseam/adapters/python.py", "codeseam/adapters"),
        ("packages/engine/src/core/rules.py", "packages/engine"),
        ("tests/test_relation_context.py", "tests"),
        ("app.py", "app.py"),
    ],
)
def test_layer_path_uses_conventional_roots_without_hardcoding_src(
    path: str,
    expected: str,
) -> None:
    assert layer_path(path) == expected


def test_context_classifier_marks_thin_contract_methods_as_sidecar_only() -> None:
    classifications = classify_contexts(
        [
            _signature("py", "serialize", container="PythonAdapter", body_line_count=2),
            _signature("ts", "serialize", container="TypescriptAdapter", body_line_count=2),
        ],
        [_relation_pair()],
        [],
    )

    assert [item.kind for item in classifications] == ["adapter_contract_method"]
    assert classifications[0].visibility == FindingVisibility.SIDECAR_ONLY
    assert classifications[0].review_tier == ReviewTier.OBSERVATION
    assert classifications[0].summary_eligible is False


def test_context_classifier_downgrades_low_specificity_signature_only_boundaries() -> None:
    classifications = classify_contexts(
        [
            _signature(
                "ts",
                "formatUser",
                file="src/users.ts",
                parameters=("Record<string, unknown>",),
                return_type="string",
            ),
            _signature(
                "swift",
                "describeAccount",
                file="Sources/Accounts.swift",
                parameters=("Any",),
                return_type="String",
            ),
        ],
        [],
        [],
    )

    assert [item.kind for item in classifications] == ["signature_only_boundary"]
    assert classifications[0].action == "observe"
    assert "signature_only" in classifications[0].context_tags
    assert classifications[0].boundary_specificity is BoundarySpecificity.LOW


def test_context_classifier_downgrades_wide_generic_mapper_families() -> None:
    members = [
        _signature(
            "python",
            "python_payload",
            file="src/python_payload.py",
            parameters=("Json",),
            return_type="Json",
        ),
        _signature(
            "typescript",
            "typescriptPayload",
            file="src/typescriptPayload.ts",
            parameters=("Record<string, unknown>",),
            return_type="Record<string, unknown>",
        ),
        _signature(
            "swift",
            "swiftPayload",
            file="Sources/SwiftPayload.swift",
            parameters=("[String: Any]",),
            return_type="[String: Any]",
        ),
        _signature(
            "rust",
            "rust_payload",
            file="src/rust_payload.rs",
            parameters=("HashMap<String, serde_json::Value>",),
            return_type="serde_json::Value",
        ),
        _signature(
            "python",
            "other_payload",
            file="src/other_payload.py",
            parameters=("dict[str, object]",),
            return_type="dict[str, object]",
        ),
    ]

    classifications = classify_contexts(
        members,
        [_relation_pair(relation_kind=RelationKind.SAME_SKELETON_DIFFERENT_LITERALS)],
        [],
    )

    assert [item.kind for item in classifications] == ["generic_mapper_boundary"]
    assert classifications[0].review_tier == ReviewTier.OBSERVATION
    assert classifications[0].visibility == FindingVisibility.SIDECAR_ONLY
    assert classifications[0].summary_eligible is False
    assert "mapping_payload" in classifications[0].context_tags


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            FixtureContextExpectation(
                fixtures=("adapter_protocol_methods.py",),
                language="Python",
                symbols=("extract_analysis",),
                relation_kind=RelationKind.NONE,
                expected_kind="adapter_contract_method",
                expected_visibility=FindingVisibility.SIDECAR_ONLY,
                expected_review_tier=ReviewTier.OBSERVATION,
                expected_summary_eligible=False,
                expected_action=ActionKind.OBSERVE,
                required_tags=("adapter_contract_method", "intentional_polymorphism"),
            ),
            id="adapter-contract-method",
        ),
        pytest.param(
            FixtureContextExpectation(
                fixtures=("target_draft_builders.py",),
                language="Python",
                symbols=("build_signature_drafts", "build_policy_constant_drafts"),
                relation_kind=RelationKind.COMMON_WRAPPER_DIFFERENT_CORE,
                expected_kind="shared_lifecycle_different_payload",
                expected_visibility=FindingVisibility.SUMMARY_GROUPED,
                expected_review_tier=ReviewTier.TRACKING_SIGNAL,
                expected_summary_eligible=True,
                expected_action=ActionKind.RECORD_SHARED_CONCERN,
                required_tags=("shared_lifecycle", "different_payload"),
            ),
            id="shared-lifecycle-different-payload",
        ),
        pytest.param(
            FixtureContextExpectation(
                fixtures=("duration_label.py", "member_label.py", "markdown_helpers.py"),
                language="Python",
                symbols=("_duration_label", "_member_label", "md_text", "md_code"),
                expected_kind="signature_only_boundary",
                expected_visibility=FindingVisibility.SIDECAR_ONLY,
                expected_review_tier=ReviewTier.OBSERVATION,
                expected_summary_eligible=False,
                expected_action=ActionKind.OBSERVE,
                required_tags=("generic_boundary", "signature_only"),
            ),
            id="generic-formatter-boundary",
        ),
        pytest.param(
            FixtureContextExpectation(
                fixtures=("target_section_renderers.py",),
                language="Python",
                symbols=("_evidence_lines", "_pair_lines"),
                expected_kind="render_section_family",
                expected_visibility=FindingVisibility.SUMMARY_GROUPED,
                expected_review_tier=ReviewTier.TRACKING_SIGNAL,
                expected_summary_eligible=True,
                expected_action=ActionKind.RECORD_SHARED_CONCERN,
                required_tags=("render_section_family", "bounded_section_lines"),
            ),
            id="render-section-family",
        ),
    ],
)
def test_documented_low_info_fixtures_match_expected_contexts(
    case: FixtureContextExpectation,
) -> None:
    members = _fixture_signatures_for_symbols(case.fixtures, case.language, case.symbols)
    relation_pairs = (
        [] if case.relation_kind is None else [_relation_pair(relation_kind=case.relation_kind)]
    )

    classifications = classify_contexts(members, relation_pairs, [])

    assert len(classifications) == 1, case.fixtures
    classification = classifications[0]
    assert classification.kind == case.expected_kind, case.fixtures
    assert classification.visibility == case.expected_visibility, case.fixtures
    assert classification.review_tier == case.expected_review_tier, case.fixtures
    assert classification.summary_eligible is case.expected_summary_eligible, case.fixtures
    assert classification.action == case.expected_action, case.fixtures
    assert set(case.required_tags) <= set(classification.context_tags), case.fixtures


def test_context_classifier_groups_collection_render_section_families() -> None:
    classifications = classify_contexts(
        [
            _signature("ts", "userSectionLines", return_type="Array<string>"),
            _signature("rust", "account_section_lines", return_type="Vec<String>"),
            _signature("swift", "profileSectionLines", return_type="[String]"),
        ],
        [],
        [],
    )

    assert [item.kind for item in classifications] == ["render_section_family"]
    assert classifications[0].visibility == FindingVisibility.SUMMARY_GROUPED
    assert classifications[0].review_tier == ReviewTier.TRACKING_SIGNAL
    assert classifications[0].summary_eligible is True


def test_context_classifier_tracks_broad_generic_predicate_families() -> None:
    classifications = classify_contexts(
        [
            _signature(
                "py",
                "_same_statements",
                file="src/relations/candidates.py",
                parameters=("MemberFeatures", "MemberFeatures"),
                return_type="bool",
                statement_sequence=("RETURN:COMPARE",),
            ),
            _signature(
                "py",
                "_compatible_members",
                file="src/relations/normalization.py",
                parameters=("MemberFeatures", "MemberFeatures"),
                return_type="bool",
                statement_sequence=("RETURN:BOOL",),
            ),
            _signature(
                "py",
                "same_module_scope_features",
                file="src/relations/scoring.py",
                parameters=("MemberFeatures", "MemberFeatures"),
                return_type="bool",
                statement_sequence=("RETURN:COMPARE",),
            ),
            _signature(
                "py",
                "same_call_multiset_features",
                file="src/relations/similarity.py",
                parameters=("MemberFeatures", "MemberFeatures"),
                return_type="bool",
                statement_sequence=("RETURN:BOOL",),
            ),
        ],
        [_relation_pair(relation_kind=RelationKind.COMMON_WRAPPER_DIFFERENT_CORE)],
        [],
    )

    assert [item.kind for item in classifications] == ["generic_predicate_family"]
    assert classifications[0].review_tier == ReviewTier.TRACKING_SIGNAL
    assert classifications[0].visibility == FindingVisibility.SUMMARY_GROUPED
    assert classifications[0].action == ActionKind.RECORD_SHARED_CONCERN


def test_boundary_specificity_marks_structured_output_boundaries_as_medium() -> None:
    classifications = classify_contexts(
        [
            _signature(
                "ts",
                "targetSection",
                parameters=("Json",),
                return_type="Array<FindingDraft>",
            ),
            _signature(
                "rust",
                "target_section",
                parameters=("Json",),
                return_type="Vec<FindingDraft>",
            ),
            _signature(
                "swift",
                "targetSectionItems",
                parameters=("Json",),
                return_type="[FindingDraft]",
            ),
        ],
        [],
        [],
    )

    assert [item.kind for item in classifications] == ["render_section_family"]
    assert classifications[0].boundary_specificity is BoundarySpecificity.MEDIUM


def test_fixture_generic_formatters_remain_sidecar_without_corroboration() -> None:
    signatures = _fixture_signatures("generic_formatters.py", "Python")

    classifications = classify_contexts(signatures, [], [])

    assert [item.kind for item in classifications] == ["signature_only_boundary"]
    assert classifications[0].visibility == FindingVisibility.SIDECAR_ONLY
    assert classifications[0].summary_eligible is False


def test_fixture_tiny_helpers_with_shared_name_and_call_are_refactorable() -> None:
    signatures = {
        signature.symbol: signature
        for signature in _fixture_signatures("corroborated_tiny_helpers.py", "Python")
        if signature.symbol in {"format_member", "format_target"}
    }
    assert set(signatures) == {"format_member", "format_target"}
    members = [signatures["format_member"], signatures["format_target"]]

    cache = MemberFeatureCache(members)
    relation = pairs.relation_pair_from_features(
        cache.get(members[0]),
        cache.get(members[1]),
        action_builder=pair_actions,
    )

    assert relation is not None
    assert relation.relation_kind == RelationKind.BODY_PARAMETERIZED
    assert relation.recommended_action == ActionKind.CONSOLIDATE_CLONE
    assert (
        ActionKind.CONSOLIDATE_CLONE,
        ActionStatus.RECOMMENDED,
    ) in {(action.kind, action.status) for action in relation.refactor_action_candidates}


def test_fixture_render_section_needs_two_corroborating_signals_for_summary() -> None:
    signatures = _fixture_signatures("render_sections.ts", "TypeScript")

    classifications = classify_contexts(signatures, [], [])

    assert [item.kind for item in classifications] == ["render_section_family"]
    assert classifications[0].visibility == FindingVisibility.SUMMARY_GROUPED
    assert classifications[0].summary_eligible is True
    assert {
        "same_module",
        "method_name_family",
    } <= set(classifications[0].corroborating_signals)


def test_context_classifier_marks_shared_lifecycle_with_different_payloads() -> None:
    classifications = classify_contexts(
        [
            _signature(
                "ts",
                "buildUserTarget",
                return_type="Finding",
                statement_sequence=("CALL:prepare", "ASSIGN:user", "RETURN:target"),
            ),
            _signature(
                "rust",
                "build_account_target",
                return_type="Finding",
                statement_sequence=("CALL:prepare", "ASSIGN:account", "RETURN:target"),
            ),
        ],
        [_relation_pair(relation_kind=RelationKind.COMMON_WRAPPER_DIFFERENT_CORE)],
        [],
    )

    assert [item.kind for item in classifications] == ["shared_lifecycle_different_payload"]
    assert classifications[0].action is ActionKind.RECORD_SHARED_CONCERN
    assert classifications[0].refactor_safety == "cautious"


def test_shared_lifecycle_without_two_signals_stays_sidecar() -> None:
    classifications = classify_contexts(
        [
            _signature(
                "ts",
                "prepareUser",
                file="src/users.ts",
                return_type="Finding",
                statement_sequence=("RETURN:user",),
            ),
            _signature(
                "ts",
                "buildAccountTarget",
                file="src/accounts.ts",
                return_type="Finding",
                statement_sequence=("RETURN:account",),
            ),
        ],
        [_relation_pair(relation_kind=RelationKind.COMMON_WRAPPER_DIFFERENT_CORE)],
        [],
    )

    assert [item.kind for item in classifications] == ["shared_lifecycle_different_payload"]
    assert classifications[0].visibility == FindingVisibility.SIDECAR_ONLY
    assert classifications[0].summary_eligible is False
    assert classifications[0].review_tier == ReviewTier.OBSERVATION


def _signature(  # noqa: PLR0913
    language: str,
    symbol: str,
    *,
    file: str = "src/sections.ts",
    container: str | None = None,
    parameters: tuple[str, ...] = ("Json",),
    return_type: str = "string",
    body_line_count: int = 4,
    statement_sequence: tuple[str, ...] = ("RETURN:ARG0",),
    call_tokens: tuple[str, ...] = (),
) -> SignatureCore:
    shape = f"fn({','.join(parameters)})->{return_type}"
    return SignatureCore(
        language=language,
        language_family=LanguageFamily.PYTHON if language == "python" else LanguageFamily.UNKNOWN,
        adapter=AdapterId.UNKNOWN,
        file=file,
        symbol=symbol,
        normalized_symbol=symbol,
        container=container,
        start_line=1,
        end_line=body_line_count,
        role="source",
        type_source=SignatureTypeSource.DECLARED_SYNTAX,
        parameters=parameters,
        return_type=return_type,
        canonical_shape=shape,
        shape_hash=shape,
        body_line_count=body_line_count,
        body_shape_hash=f"body:{symbol}",
        body_tree_node_count=0,
        statement_sequence=statement_sequence,
        call_tokens=call_tokens,
        control_context_vector=(),
        return_signature=tuple(item for item in statement_sequence if item.startswith("RETURN:")),
        try_statement_count=0,
        raise_statement_count=0,
        signature_id=f"sig:{language}:{symbol}",
        function_id=f"fn:{language}:{symbol}",
    )


def _relation_member(language: str, file: str, *, role: str = "") -> RelationMemberContext:
    return RelationMemberContext(
        signature_id=f"sig:{language}:{file}",
        function_id=None,
        file=file,
        symbol="member",
        start_line=1,
        language=language,
        return_type="None",
        parameters=(),
        role=role,
    )


def _fixture_signatures(path: str, language: str) -> list[SignatureCore]:
    fixture = FIXTURES / path
    adapter = default_language_registry().adapter_for_language(language)
    assert adapter is not None
    records = adapter.extract_analysis(
        LanguageAnalysisContext(
            fixture,
            f"tests/fixtures/low_info_noise/{path}",
            "source",
            language,
        )
    ).signatures
    return [signature_core_from_record(record) for record in records]


def _fixture_signatures_for_symbols(
    paths: tuple[str, ...],
    language: str,
    symbols: tuple[str, ...],
) -> list[SignatureCore]:
    selected = [
        signature
        for path in paths
        for signature in _fixture_signatures(path, language)
        if signature.symbol in symbols
    ]
    assert {signature.symbol for signature in selected} == set(symbols)
    return selected


def _relation_pair(
    *,
    relation_kind: RelationKind = RelationKind.NONE,
    body_hash_match: bool = False,
    tree_similarity: float = 0.2,
    name_similarity: float = 0.2,
) -> RelationPair:
    return cast(
        RelationPair,
        SimpleNamespace(
            relation_kind=relation_kind,
            flags=SimpleNamespace(body_hash_match=body_hash_match),
            tree=SimpleNamespace(tree_similarity=tree_similarity),
            scores=SimpleNamespace(name=name_similarity),
        ),
    )
