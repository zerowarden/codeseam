"""Drafts for identical, drifted and scattered policy constants."""

from __future__ import annotations

from codeseam.analysis.clusters import (
    PolicyConstantCluster,
    PolicyConstantMatch,
)
from codeseam.analysis.findings.common import dedupe
from codeseam.analysis.findings.constants import (
    EVIDENCE_KIND_POLICY_CONSTANT_CLUSTER,
    EVIDENCE_OVERLAP_POLICY_CONSTANT,
)
from codeseam.analysis.findings.definitions import FindingTargetType
from codeseam.analysis.findings.locations import line_span
from codeseam.analysis.findings.models import (
    EvidenceItem,
    FindingDraft,
    FindingLocation,
    FindingMetrics,
)
from codeseam.analysis.relations import (
    AbstractionKind,
    EvidenceKind,
)
from codeseam.analysis.signatures import (
    ExtractionConfidence,
    NormalizationLevel,
    PolicyConstant,
)
from codeseam.caveat_msg import EVIDENCE_CAVEATS

POLICY_CONSTANT_RELATEDNESS = 1.0


POLICY_CONSTANT_REFACTORABILITY = 0.92


POLICY_CONSTANT_CONFIDENCE = 0.98


POLICY_CONSTANT_RISK = 0.04


# Unifying drifted copies changes what some callers get; unifying differently
# named copies asserts the names mean one rule. Either is a medium risk, above
# the introduction-risk ceiling, so it is recorded for review, never edited.
POLICY_CONSTANT_DIVERGENT_RISK = 0.35


POLICY_CONSTANT_MATCH_TEXT = {
    PolicyConstantMatch.IDENTICAL: (
        "Duplicated policy constant",
        "Multiple source modules define the same top-level policy constant name.",
        "The duplicated constants have identical structured literal values.",
    ),
    PolicyConstantMatch.DRIFTED: (
        "Drifted policy constant",
        "Multiple source modules define the same top-level policy constant name.",
        "The copies share most items but their values have diverged.",
    ),
    PolicyConstantMatch.SCATTERED: (
        "Scattered policy literal",
        "The same structured literal is defined under different constant names.",
        "The names may describe one rule, or unrelated rules that happen to agree.",
    ),
}


def build_policy_constant_drafts(
    clusters: tuple[PolicyConstantCluster, ...],
) -> list[FindingDraft]:
    targets = []
    for cluster in clusters:
        members = list(cluster.members)
        files = dedupe(member.file for member in members)
        evidence_kinds = list(cluster.evidence_kinds)
        actions = list(cluster.refactor_action_candidates)
        locations = _policy_constant_locations(members)
        title, *reasons = POLICY_CONSTANT_MATCH_TEXT[cluster.match]
        targets.append(
            FindingDraft(
                target_type=FindingTargetType.SIGNATURE_SHAPE,
                title=f"{title} {_policy_constant_symbol(cluster)}",
                severity="high",
                confidence=float(cluster.confidence),
                files=files,
                locations=locations,
                metrics=FindingMetrics(
                    member_count=cluster.member_count,
                    canonical_shape=cluster.canonical_shape,
                    policy_constant_duplicate_count=1,
                    cluster_scope="same_language",
                    normalization_level=NormalizationLevel.LITERAL_POLICY,
                    language_count=1,
                    adapter_count=1,
                    min_extraction_confidence=ExtractionConfidence.HIGH,
                    structural_relation_pair_count=1,
                    same_role_relation_count=1,
                    lead_relatedness_score=POLICY_CONSTANT_RELATEDNESS,
                    lead_refactorability_score=POLICY_CONSTANT_REFACTORABILITY,
                    lead_confidence_score=POLICY_CONSTANT_CONFIDENCE,
                    lead_risk_score=(
                        POLICY_CONSTANT_RISK
                        if cluster.match is PolicyConstantMatch.IDENTICAL
                        else POLICY_CONSTANT_DIVERGENT_RISK
                    ),
                ),
                evidence=[
                    EvidenceItem(EVIDENCE_KIND_POLICY_CONSTANT_CLUSTER, id=cluster.cluster_id),
                    EvidenceItem(EvidenceKind.POLICY_CONSTANT_DUPLICATE, id=cluster.cluster_id),
                ],
                reasons=[*reasons, "Policy rules should have one source of truth."],
                risk="low" if cluster.match is PolicyConstantMatch.IDENTICAL else "medium",
                direction=(
                    "Move the policy literal to a shared common module or configuration source "
                    "and import it at each call site."
                ),
                overlaps={EVIDENCE_OVERLAP_POLICY_CONSTANT: (cluster.cluster_id,)},
                member_count=cluster.member_count,
                line_span=line_span(locations),
                non_claims=list(cluster.non_claims or EVIDENCE_CAVEATS),
                abstraction_kind=cluster.abstraction_kind or AbstractionKind.MOVE_MODULE,
                evidence_kinds=evidence_kinds or [EvidenceKind.POLICY_CONSTANT_DUPLICATE],
                refactor_action_candidates=actions,
                refactor_action_summary=cluster.refactor_action_summary,
            )
        )
    return targets


def _policy_constant_symbol(cluster: PolicyConstantCluster) -> str:
    symbols = dedupe(member.symbol for member in cluster.members if member.symbol)
    return " / ".join(symbols) or cluster.canonical_shape or "unknown"


def _policy_constant_locations(members: list[PolicyConstant]) -> list[FindingLocation]:
    return [
        FindingLocation(
            file=member.file,
            start_line=member.start_line,
            end_line=member.end_line,
            source="policy_literal",
            kind="policy_constant",
            symbol=member.symbol,
            message="Duplicated top-level policy constant with identical literal value.",
        )
        for member in members
    ]


__all__ = [
    "POLICY_CONSTANT_CONFIDENCE",
    "POLICY_CONSTANT_DIVERGENT_RISK",
    "POLICY_CONSTANT_MATCH_TEXT",
    "POLICY_CONSTANT_REFACTORABILITY",
    "POLICY_CONSTANT_RELATEDNESS",
    "POLICY_CONSTANT_RISK",
    "build_policy_constant_drafts",
]
