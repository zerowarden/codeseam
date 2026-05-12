from __future__ import annotations

from typing import Any

from codeseam.analysis.assessment.definitions import (
    AssessmentBand,
    AssessmentGate,
    EvidenceQuality,
    EvidenceStrength,
    ExtractionConfidence,
    RecommendationStatus,
)
from codeseam.analysis.assessment.models import (
    AbstractionFit,
    AbstractionRisk,
    ActionAssessment,
    AssessmentBreakdown,
    ContextClassification,
    DetectionConfidence,
    EvidenceSummary,
    MaintenancePayoff,
    ReviewAssessment,
    SemanticRisk,
)
from codeseam.analysis.assessment.policy import (
    DEFAULT_ASSESSMENT_VALUES,
    AssessmentPolicy,
    ConfigSection,
    DetectionPolicy,
    FitPolicy,
    PayoffPolicy,
    RecommendationCap,
    RelationEvidencePolicy,
    SemanticEvidencePolicy,
    SemanticRoleCapPolicy,
)


def build_findings(*args: Any, **kwargs: Any) -> Any:
    """Lazy package-boundary facade for the findings assessment pipeline."""

    from codeseam.analysis.assessment.findings import build_findings as _build_findings  # noqa: I001, PLC0415

    return _build_findings(*args, **kwargs)


__all__ = [
    "DEFAULT_ASSESSMENT_VALUES",
    "AbstractionFit",
    "AbstractionRisk",
    "ActionAssessment",
    "AssessmentBand",
    "AssessmentBreakdown",
    "AssessmentGate",
    "AssessmentPolicy",
    "build_findings",
    "ConfigSection",
    "ContextClassification",
    "DetectionConfidence",
    "DetectionPolicy",
    "EvidenceSummary",
    "EvidenceQuality",
    "EvidenceStrength",
    "ExtractionConfidence",
    "FitPolicy",
    "MaintenancePayoff",
    "PayoffPolicy",
    "RecommendationStatus",
    "RecommendationCap",
    "RelationEvidencePolicy",
    "ReviewAssessment",
    "SemanticEvidencePolicy",
    "SemanticRisk",
    "SemanticRoleCapPolicy",
]
