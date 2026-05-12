from __future__ import annotations

from codeseam.analysis.relations.policy import RELATION_ASSESSMENT_POLICY


def has_error_evidence(shape: tuple[object, ...]) -> bool:
    caveats, try_count, raise_count = shape
    return bool(caveats or try_count or raise_count)


def parameter_cost(count: int) -> float:
    if count <= RELATION_ASSESSMENT_POLICY.manageable_parameter_count:
        return 0.0
    return min(
        1.0,
        (count - RELATION_ASSESSMENT_POLICY.manageable_parameter_count)
        / RELATION_ASSESSMENT_POLICY.high_parameter_count,
    )


__all__ = ["has_error_evidence", "parameter_cost"]
