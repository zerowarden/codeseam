from __future__ import annotations

from dataclasses import dataclass

from codeseam.analysis.assessment.definitions import (
    AssessmentBand,
    AssessmentGate,
    EvidenceQuality,
    EvidenceStrength,
    FindingActionStatus,
    FindingReviewVisibility,
    FindingVisibility,
    RecommendationStatus,
    ReviewTier,
)
from codeseam.analysis.relations.models import ActionKind
from codeseam.analysis.signatures import BoundarySpecificity


@dataclass(frozen=True, slots=True)
class AbstractionRisk:
    """How risky it is to perform an abstraction"""

    kind: str
    message: str = ""


@dataclass(frozen=True, slots=True)
class DetectionConfidence:
    """How likely it is that the relation is real, independent of refactoring."""

    score: float
    evidence_quality: EvidenceQuality
    signals: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EvidenceSummary:
    """Typed relation-evidence summary used by assessment scorers."""

    classes: tuple[str, ...]

    @classmethod
    def from_classes(cls, values: tuple[str, ...]) -> EvidenceSummary:
        return cls(tuple(sorted(set(values))))

    def has(self, evidence_class: str) -> bool:
        return evidence_class in self.classes


@dataclass(frozen=True, slots=True)
class AbstractionFit:
    """How well the repeated code admits one clean shared abstraction."""

    score: float
    band: AssessmentBand
    cost: float
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SemanticRisk:
    """How likely consolidation is to change meaning or create a bad abstraction."""

    score: float
    band: AssessmentBand
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MaintenancePayoff:
    """Whether the finding is worth attention."""

    score: float
    band: AssessmentBand
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ActionAssessment:
    action_kind: ActionKind
    status: RecommendationStatus
    preconditions_failed: tuple[AssessmentGate, ...]
    detection_confidence: float
    abstraction_fit: float
    semantic_risk: float
    abstraction_cost: float
    recommendation_confidence: float
    recommendation_score: float
    requested_action_kind: ActionKind | None = None
    preconditions_passed: tuple[AssessmentGate, ...] = ()
    fallback_reasons: tuple[AssessmentGate, ...] = ()


@dataclass(frozen=True, slots=True)
class ContextClassification:
    kind: str
    context_tags: tuple[str, ...]
    visibility: FindingVisibility
    summary_eligible: bool
    action: ActionKind
    refactor_value: str
    refactor_safety: str
    downgrade_reasons: tuple[str, ...]
    review_tier: ReviewTier | None = None
    evidence_strength: EvidenceStrength = EvidenceStrength.NONE
    boundary_specificity: BoundarySpecificity | None = None
    corroborating_signals: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AssessmentBreakdown:
    detection_confidence: DetectionConfidence
    abstraction_fit: AbstractionFit
    semantic_risk: SemanticRisk
    maintenance_payoff: MaintenancePayoff
    action_recommendation: ActionAssessment


@dataclass(frozen=True, slots=True)
class ReviewAssessment:
    review_tier: ReviewTier
    review_score: float
    action_status: FindingActionStatus
    primary_action: ActionKind
    visibility: FindingReviewVisibility
    summary_eligible: bool
    evidence_strength: EvidenceStrength
    evidence_classes: tuple[str, ...]
    breakdown: AssessmentBreakdown
    rationale: tuple[str, ...]
    summary_reason: str


__all__ = [
    "AbstractionFit",
    "AbstractionRisk",
    "ActionAssessment",
    "AssessmentBreakdown",
    "ContextClassification",
    "DetectionConfidence",
    "EvidenceSummary",
    "MaintenancePayoff",
    "ReviewAssessment",
    "SemanticRisk",
]
