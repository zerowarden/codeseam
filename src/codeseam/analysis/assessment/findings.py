from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import replace

from codeseam.analysis.assessment.assess import assess_target
from codeseam.analysis.assessment.policy import AssessmentPolicy
from codeseam.analysis.clusters import Clusters
from codeseam.analysis.findings import (
    Finding,
    FindingLocation,
)
from codeseam.analysis.findings.block_drafts import (
    build_intra_function_duplicate_drafts,
    build_shared_block_drafts,
)
from codeseam.analysis.findings.definitions import REVIEW_TIER_ORDER, ReviewTier
from codeseam.analysis.findings.drafts import build_signature_drafts
from codeseam.analysis.findings.identity import with_target_identity
from codeseam.analysis.findings.policy_drafts import build_policy_constant_drafts
from codeseam.analysis.findings.semantic_evidence import SemanticEvidenceIndex
from codeseam.analysis.repository import RepositoryFacts
from codeseam.analysis.signatures import SignatureAnalysis
from codeseam.semantics import SemanticEnrichmentRun


def build_findings(
    signature_clusters: Clusters,
    facts: RepositoryFacts,
    assessment_policy: AssessmentPolicy,
    semantic_enrichment: SemanticEnrichmentRun | None = None,
    signatures: Sequence[SignatureAnalysis] | None = None,
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
    ordered = sorted(
        _drop_subsumed_findings(_dedupe_equivalent_findings(findings)), key=finding_sort_key
    )
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


ACTIONABLE_TIERS = frozenset({ReviewTier.RECOMMENDED_EDIT, ReviewTier.REVIEW_CANDIDATE})


def _drop_subsumed_findings(findings: list[Finding]) -> list[Finding]:
    """Drop a finding when an actionable one already covers all of its members.

    A cluster of 21 identical helpers and a 12-member subset of it with the
    same action tell the reader one thing. Only a recommended edit or review
    candidate subsumes: a broad maintenance-note family must not hide a
    precise, smaller cluster. A subset with a different action or a higher
    tier is kept.
    """

    surfaces = [
        (finding, frozenset(_location_identity(location) for location in finding.locations))
        for finding in findings
    ]
    return [
        finding
        for finding, members in surfaces
        if not any(
            members < other_members
            and other.primary_action is finding.primary_action
            and other.target_type is finding.target_type
            and other.review_tier in ACTIONABLE_TIERS
            and REVIEW_TIER_ORDER[other.review_tier] <= REVIEW_TIER_ORDER[finding.review_tier]
            for other, other_members in surfaces
        )
    ]


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
