from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from codeseam.analysis import (
    AssessmentBand,
    AssessmentPolicy,
    EvidenceSummary,
    FindingMetrics,
    SemanticEvidenceIndex,
    SemanticEvidenceMetrics,
    evidence_summary,
    score_abstraction_fit,
    score_detection_confidence,
    score_semantic_risk,
)
from codeseam.config import load_config
from codeseam.semantics import (
    SemanticCallTarget,
    SemanticEnrichedItem,
    SemanticEnrichmentResult,
    SemanticEnrichmentRun,
    SemanticMode,
    SemanticProjectSummary,
    SemanticProviderMetadata,
    SemanticProviderStatus,
    SemanticSymbolIdentity,
)

POLICY = AssessmentPolicy.from_config(load_config(Path("/repo")).data)


@dataclass(frozen=True)
class _Member:
    signature_id: str


@dataclass(frozen=True)
class _Pair:
    left: _Member
    right: _Member


def test_semantic_evidence_index_aggregates_shared_provider_facts() -> None:
    index = SemanticEvidenceIndex.from_run(
        _run(
            _item(
                "sig_left",
                overload_group_id="overload:parse",
                call_targets=(_call("normalize", "normalize", "src/shared.ts"),),
                symbol=SemanticSymbolIdentity(name="parse"),
            ),
            _item(
                "sig_right",
                overload_group_id="overload:parse",
                call_targets=(_call("normalize", "normalize", "src/shared.ts"),),
                symbol=SemanticSymbolIdentity(name="parse"),
            ),
        )
    )

    metrics = index.metrics_for_members(
        (_Member("sig_left"), _Member("sig_right")),
        relation_pairs=(_Pair(_Member("sig_left"), _Member("sig_right")),),
    )

    assert metrics.same_overload_group_pair_count == 1
    assert metrics.shared_call_target_pair_count == 1


def test_semantic_evidence_index_records_uncertain_provider_facts() -> None:
    index = SemanticEvidenceIndex.from_run(
        _run(
            _item(
                "sig_left",
                resolved=True,
                call_targets=(_call("read", "readFile", "src/fs.ts"),),
                caveats=("provider_warning",),
            ),
            _item(
                "sig_right",
                resolved=False,
                declaration_only=True,
                ownership_ambiguous=True,
                call_targets=(_call("read", "readFileSync", "src/fs.ts"),),
                caveats=("unsupported_node_kind",),
            ),
        )
    )

    metrics = index.metrics_for_members(
        (_Member("sig_left"), _Member("sig_right")),
        relation_pairs=(_Pair(_Member("sig_left"), _Member("sig_right")),),
    )

    assert metrics.unresolved_item_count == 1
    assert metrics.ambiguous_ownership_count == 1
    assert metrics.declaration_only_count == 1
    assert metrics.divergent_call_target_pair_count == 1


def test_semantic_support_boosts_structural_detection_but_not_signature_only() -> None:
    base = FindingMetrics(
        member_count=2,
        structural_relation_pair_count=1,
        max_relation_confidence_score=0.50,
    )
    supported = replace(
        base,
        semantic_evidence=SemanticEvidenceMetrics(shared_call_target_pair_count=1),
    )

    base_evidence = evidence_summary(
        metrics=base,
        evidence_kinds=(),
        relation_pairs=(),
        has_signature_overlap=True,
    )
    supported_evidence = evidence_summary(
        metrics=supported,
        evidence_kinds=(),
        relation_pairs=(),
        has_signature_overlap=True,
    )

    assert (
        score_detection_confidence(
            supported, evidence=supported_evidence, policy=POLICY.detection
        ).score
        > score_detection_confidence(base, evidence=base_evidence, policy=POLICY.detection).score
    )

    signature_only = FindingMetrics(
        member_count=2,
        semantic_evidence=SemanticEvidenceMetrics(shared_call_target_pair_count=1),
    )
    detection = score_detection_confidence(
        signature_only,
        evidence=EvidenceSummary.from_classes(("semantic_shared_call_target",)),
        policy=POLICY.detection,
    )

    assert detection.score == POLICY.detection.signature_only_base_confidence


def test_semantic_support_improves_fit_only_when_common_region_exists() -> None:
    base = FindingMetrics(
        member_count=2,
        structural_relation_pair_count=1,
        max_refactorability_score=0.50,
    )
    no_region = score_abstraction_fit(
        replace(
            base,
            semantic_evidence=SemanticEvidenceMetrics(shared_call_target_pair_count=1),
        ),
        POLICY,
    )
    with_region = score_abstraction_fit(
        replace(base, max_stable_statement_count=2),
        POLICY,
    )
    supported_region = score_abstraction_fit(
        replace(
            base,
            max_stable_statement_count=2,
            semantic_evidence=SemanticEvidenceMetrics(shared_call_target_pair_count=1),
        ),
        POLICY,
    )

    assert no_region.score == score_abstraction_fit(base, POLICY).score
    assert supported_region.score > with_region.score
    assert "semantic_shared_implementation_evidence" in supported_region.reasons


def test_uncertain_semantic_facts_increase_risk_without_language_specific_rules() -> None:
    risk = score_semantic_risk(
        FindingMetrics(
            semantic_evidence=SemanticEvidenceMetrics(
                declaration_only_count=1,
                ambiguous_ownership_count=1,
                divergent_call_target_pair_count=1,
            ),
        ),
        (),
        POLICY,
    )

    assert risk.score >= POLICY.semantic_evidence.divergent_call_target_risk_floor
    assert risk.band is AssessmentBand.MEDIUM
    assert risk.reasons == (
        "semantic_declaration_surface",
        "semantic_ambiguous_ownership",
        "semantic_divergent_call_target",
    )


def _run(*items: SemanticEnrichedItem) -> SemanticEnrichmentRun:
    return SemanticEnrichmentRun(
        mode=SemanticMode.PROJECT,
        status=SemanticProviderStatus.READY,
        results=(
            SemanticEnrichmentResult(
                request_id="request-1",
                language="TypeScript",
                mode=SemanticMode.PROJECT,
                status=SemanticProviderStatus.READY,
                provider=SemanticProviderMetadata(name="test_provider", mode=SemanticMode.PROJECT),
                project=SemanticProjectSummary(project_cache_key="sha256:project"),
                items=items,
            ),
        ),
    )


def _item(
    signature_id: str,
    **overrides: Any,
) -> SemanticEnrichedItem:
    values: dict[str, Any] = {
        "resolved": True,
        "ownership_ambiguous": False,
        "symbol": None,
        "overload_group_id": None,
        "declaration_only": False,
        "call_targets": (),
        "caveats": (),
    }
    values.update(overrides)
    return SemanticEnrichedItem(
        signature_id=signature_id,
        **values,
    )


def _call(token: str, symbol: str, file: str) -> SemanticCallTarget:
    return SemanticCallTarget(
        call_token=token,
        resolved=True,
        symbol_name=symbol,
        declaration_file=file,
    )
