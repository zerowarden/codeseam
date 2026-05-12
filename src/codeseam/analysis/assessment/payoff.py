from __future__ import annotations

from codeseam.analysis.assessment.bands import assessment_band
from codeseam.analysis.assessment.models import MaintenancePayoff
from codeseam.analysis.assessment.policy import AssessmentPolicy, PayoffPolicy
from codeseam.analysis.findings import FindingMetrics
from codeseam.platform import clamp01, noisy_or, ramp, ramp_count


def score_maintenance_payoff(
    metrics: FindingMetrics,
    *,
    roles: list[str],
    line_span: int,
    policy: AssessmentPolicy,
    distinct_file_count: int | None = None,
) -> MaintenancePayoff:
    """Answer whether the finding deserves human attention.

    Payoff is intentionally separate from detection confidence and abstraction
    fit. It combines relation quality, maintenance surface, and code exposure
    so broad weak recurrences cannot become important by additive accretion.
    """
    anchors = policy.payoff
    reasons: list[str] = []

    quality, quality_reason = _relation_quality(metrics, anchors)
    reasons.append(quality_reason)

    recurrence = ramp_count(
        metrics.member_count,
        starts_at=anchors.recurrence_starts_at_members,
        high_at=anchors.recurrence_high_at_members,
    )
    if recurrence:
        reasons.append("recurrent_members")

    volume = ramp(line_span, low=anchors.material_line_span, high=anchors.high_line_span)
    if metrics.intra_function_duplicate_block_count:
        volume = max(
            volume,
            ramp(
                metrics.intra_function_duplicate_line_count,
                low=anchors.local_duplicate_material_line_span,
                high=anchors.local_duplicate_high_line_span,
            ),
        )
    if volume:
        reasons.append("material_line_span")

    spread = 0.0
    if distinct_file_count is not None:
        spread = ramp_count(
            distinct_file_count,
            starts_at=anchors.spread_starts_at_files,
            high_at=anchors.spread_high_at_files,
        )
        if spread:
            reasons.append("file_spread")

    exposure, cap, exposure_reason = _exposure_multiplier_and_cap(roles, anchors)
    reasons.append(exposure_reason)

    score = quality * noisy_or(recurrence, volume, spread) * exposure
    score = round(min(clamp01(score), cap), policy.precision)
    return MaintenancePayoff(
        score,
        assessment_band(
            score,
            high=policy.high_band_threshold,
            medium=policy.medium_band_threshold,
        ),
        tuple(reasons),
    )


def _relation_quality(metrics: FindingMetrics, anchors: PayoffPolicy) -> tuple[float, str]:
    if metrics.intra_function_duplicate_block_count:
        return 1.0, "intra_function_duplicate"
    if metrics.structural_duplicate_pair_count:
        return 1.0, "structural_duplicate"
    if metrics.structural_relation_pair_count:
        return anchors.structural_relation_quality, "structural_relation"
    if metrics.member_count >= anchors.recurrence_starts_at_members:
        return anchors.signature_only_quality, "signature_only_recurrence"
    return 0.0, "no_relation_quality"


def _exposure_multiplier_and_cap(
    roles: list[str],
    anchors: PayoffPolicy,
) -> tuple[float, float, str]:
    role_set = set(roles)
    if role_set & {"generated", "vendor", "build_output"}:
        return 1.0, anchors.generated_vendor_cap, "generated_vendor_or_build_output"
    if roles and role_set <= {"test", "fixture"}:
        return anchors.test_fixture_exposure, 1.0, "test_or_fixture_only"
    if "source" in role_set:
        return 1.0, 1.0, "source_code"
    return anchors.unknown_role_exposure, 1.0, "unknown_role"


__all__ = ["score_maintenance_payoff"]
