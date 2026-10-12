"""Which findings each report surface carries, decided on typed findings."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from codeseam.analysis.assessment.definitions import FindingActionStatus, ReviewTier
from codeseam.analysis.findings.models import Finding

ANALYSIS_REVIEW_TIERS = frozenset(
    {ReviewTier.RECOMMENDED_EDIT, ReviewTier.REVIEW_CANDIDATE, ReviewTier.MAINTENANCE_NOTE}
)


@dataclass(frozen=True, slots=True)
class SurfacedFindings:
    """Ranked findings split into the analysis sidecar and observations.

    `agent_summary` is the analysis subset listed in the summary and counted
    by CI; it is the assessment's `summary_eligible` decision.
    """

    ranked: tuple[Finding, ...]
    analysis: tuple[Finding, ...]
    observations: tuple[Finding, ...]
    agent_summary: tuple[Finding, ...]

    @property
    def recommended_edit_tier_count(self) -> int:
        return sum(item.review_tier is ReviewTier.RECOMMENDED_EDIT for item in self.ranked)

    @property
    def recommended_edit_count(self) -> int:
        return sum(
            item.action_status is FindingActionStatus.RECOMMENDED_EDIT
            for item in self.agent_summary
        )


def surface_findings(findings: Sequence[Finding]) -> SurfacedFindings:
    """Keep the first finding per target ID, in rank order, and split it by tier."""

    seen: set[str] = set()
    ranked: list[Finding] = []
    for item in findings:
        if item.target_id not in seen:
            seen.add(item.target_id)
            ranked.append(item)
    analysis = tuple(item for item in ranked if item.review_tier in ANALYSIS_REVIEW_TIERS)
    observations = tuple(item for item in ranked if item.review_tier not in ANALYSIS_REVIEW_TIERS)
    return SurfacedFindings(
        ranked=tuple(ranked),
        analysis=analysis,
        observations=observations,
        agent_summary=tuple(item for item in analysis if item.summary_eligible),
    )


__all__ = ["ANALYSIS_REVIEW_TIERS", "SurfacedFindings", "surface_findings"]
