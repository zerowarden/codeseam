from __future__ import annotations

from typing import cast

from factories import agent_payload_fixture

from codeseam.analysis import AssessmentBand, AssessmentGate
from codeseam.output.serializers.findings import agent_review_target_payload


def test_agent_analysis_payload_is_lean_and_uses_failed_gates() -> None:
    payload = agent_review_target_payload(
        agent_payload_fixture(
            semantic_risk=AssessmentBand.HIGH,
            failed=(AssessmentGate.LOW_SEMANTIC_RISK,),
        )
    )

    assert "metrics" not in payload
    assert "locations" not in payload
    assert "relatedness_score" not in payload
    assert "refactorability_score" not in payload
    assert "abstraction_cost_score" not in payload
    assert "confidence" not in payload
    assessment = cast(dict[str, object], payload["assessment"])
    action = cast(dict[str, object], assessment["action_recommendation"])
    assert action["failed_gates"] == [
        {"gate": "semantic_risk", "required": "low", "actual": "high"}
    ]
    assert "preconditions_failed" not in action
