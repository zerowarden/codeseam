from __future__ import annotations

from collections import defaultdict
from dataclasses import replace

from codeseam.analysis.assessment.assess import assess_target
from codeseam.analysis.assessment.cluster import Clusters
from codeseam.analysis.assessment.definitions import REVIEW_TIER_ORDER
from codeseam.analysis.assessment.policy import AssessmentPolicy
from codeseam.analysis.findings import (
    Finding,
    FindingLocation,
)
from codeseam.analysis.findings.drafts import (
    build_intra_function_duplicate_drafts,
    build_policy_constant_drafts,
    build_shared_block_drafts,
    build_signature_drafts,
)
from codeseam.analysis.findings.identity import with_target_identity
from codeseam.analysis.findings.semantic_evidence import SemanticEvidenceIndex
from codeseam.analysis.repository import RepositoryFacts
from codeseam.analysis.signatures import SignatureAnalysis
from codeseam.semantics import SemanticEnrichmentRun


def build_findings(
    signature_clusters: Clusters,
    facts: RepositoryFacts,
    assessment_policy: AssessmentPolicy,
    semantic_enrichment: SemanticEnrichmentRun | None = None,
    signatures: list[SignatureAnalysis] | None = None,
) -> list[Finding]:
    semantic_evidence = SemanticEvidenceIndex.from_run(semantic_enrichment)
    drafts = [
        *build_policy_constant_drafts(signature_clusters.policy_constant_clusters),
        *build_signature_drafts(
            signature_clusters.clusters,
            semantic_evidence=semantic_evidence,
        ),
        *build_intra_function_duplicate_drafts(signatures or []),
        *build_shared_block_drafts(signatures or [], signature_clusters.clusters),
    ]
    findings = _with_unique_identities(
        [
            assess_target(
                draft=draft,
                roles_by_path=facts.roles_by_path,
                policy=assessment_policy,
            )
            for draft in drafts
        ]
    )
    ordered = sorted(_dedupe_equivalent_findings(findings), key=finding_sort_key)
    return [
        replace(finding, rank=index, rank_label=f"#{index}")
        for index, finding in enumerate(ordered, 1)
    ]


def finding_sort_key(finding: Finding) -> tuple[int, float, str, str]:
    return (
        REVIEW_TIER_ORDER.get(finding.review_tier, 9),
        -float(finding.review_score),
        finding.target_type.value,
        str(finding.title),
    )


def _with_unique_identities(findings: list[Finding]) -> list[Finding]:
    """Give different targets different IDs.

    IDs leave out line numbers, so two targets over same-name members of one
    file (two classes' `analyse_text`) can collide, and the output keeps only
    one of them. Colliding targets with different member locations get
    positional IDs instead.
    """

    identified = [with_target_identity(finding) for finding in findings]
    surfaces: dict[str, set[tuple[object, ...]]] = defaultdict(set)
    for finding in identified:
        surfaces[finding.target_id].add(_finding_equivalence_key(finding))
    return [
        with_target_identity(finding, positional=True)
        if len(surfaces[finding.target_id]) > 1
        else finding
        for finding in identified
    ]


def _dedupe_equivalent_findings(findings: list[Finding]) -> list[Finding]:
    """Collapse duplicate targets built through different evidence paths.

    Overlapping candidate generation paths can produce two findings over the
    exact same members. The human-facing unit is the member location set, so
    keep only the strongest finding for each exact target surface.
    """

    selected: dict[tuple[object, ...], Finding] = {}
    for finding in findings:
        key = _finding_equivalence_key(finding)
        current = selected.get(key)
        if current is None or finding_sort_key(finding) < finding_sort_key(current):
            selected[key] = finding
    return list(selected.values())


def _finding_equivalence_key(finding: Finding) -> tuple[object, ...]:
    return (
        finding.target_type,
        tuple(sorted(_location_identity(location) for location in finding.locations)),
    )


def _location_identity(location: FindingLocation) -> tuple[str, int, int, str]:
    return (
        location.file,
        location.start_line,
        location.end_line,
        location.symbol,
    )


__all__ = ["build_findings"]
