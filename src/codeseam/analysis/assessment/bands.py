from __future__ import annotations

from codeseam.analysis.assessment.definitions import AssessmentBand


def assessment_band(score: float, *, high: float, medium: float) -> AssessmentBand:
    if score >= high:
        return AssessmentBand.HIGH
    if score >= medium:
        return AssessmentBand.MEDIUM
    if score > 0:
        return AssessmentBand.LOW
    return AssessmentBand.NONE


__all__ = ["assessment_band"]
