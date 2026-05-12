from __future__ import annotations

import pytest

from codeseam.analysis import (
    EVIDENCE_ARGUMENT_NORMALIZATION_WRAPPER,
    EVIDENCE_CALL_FINGERPRINT_OVERLAP,
    EVIDENCE_CONTROL_CONTEXT_SIMILARITY,
    DetectionPolicy,
    EvidenceQuality,
    EvidenceSummary,
    ExtractionConfidence,
    FindingMetrics,
    score_detection_confidence,
)

POLICY = DetectionPolicy()


@pytest.mark.parametrize(
    ("metrics", "evidence_classes", "quality", "score", "signals"),
    [
        pytest.param(
            FindingMetrics(structural_relation_pair_count=1),
            (),
            EvidenceQuality.STRUCTURAL,
            0.30,
            ("structural_relation",),
            id="unsupported-structural-relation",
        ),
        pytest.param(
            FindingMetrics(
                structural_relation_pair_count=1,
                max_relation_confidence_score=0.70,
                max_tree_similarity=0.80,
                max_name_similarity=0.70,
            ),
            (),
            EvidenceQuality.STRUCTURAL,
            0.80,
            ("structural_relation", "tree_similarity", "name_similarity"),
            id="supported-structural-relation",
        ),
        pytest.param(
            FindingMetrics(member_count=2),
            (),
            EvidenceQuality.SIGNATURE_ONLY,
            0.18,
            ("signature_shape_recurrence",),
            id="signature-only-recurrence",
        ),
        pytest.param(
            FindingMetrics(call_fingerprint_count=2, control_context_count=2),
            (EVIDENCE_CALL_FINGERPRINT_OVERLAP, EVIDENCE_CONTROL_CONTEXT_SIMILARITY),
            EvidenceQuality.PROXY,
            0.50,
            ("call_fingerprint", "control_context"),
            id="proxy-with-support",
        ),
        pytest.param(
            FindingMetrics(structural_duplicate_pair_count=1, structural_relation_pair_count=1),
            (),
            EvidenceQuality.EXACT,
            0.90,
            ("structural_duplicate",),
            id="structural-duplicate-priority",
        ),
        pytest.param(
            FindingMetrics(member_count=2),
            (EVIDENCE_ARGUMENT_NORMALIZATION_WRAPPER,),
            EvidenceQuality.STRUCTURAL,
            0.58,
            ("argument_normalization_wrapper",),
            id="argument-normalization-unsupported",
        ),
        pytest.param(
            FindingMetrics(member_count=2),
            (EVIDENCE_ARGUMENT_NORMALIZATION_WRAPPER, EVIDENCE_CALL_FINGERPRINT_OVERLAP),
            EvidenceQuality.STRUCTURAL,
            0.72,
            ("argument_normalization_wrapper",),
            id="argument-normalization-supported",
        ),
        pytest.param(
            FindingMetrics(
                policy_constant_duplicate_count=1,
                min_extraction_confidence=ExtractionConfidence.LOW,
            ),
            (),
            EvidenceQuality.EXACT,
            0.735,
            ("policy_constant_duplicate", "low_extraction_confidence"),
            id="low-extraction-penalty",
        ),
        pytest.param(
            FindingMetrics(
                policy_constant_duplicate_count=1,
                min_extraction_confidence=ExtractionConfidence.UNKNOWN,
            ),
            (),
            EvidenceQuality.EXACT,
            0.833,
            ("policy_constant_duplicate", "unknown_extraction_confidence"),
            id="unknown-extraction-penalty",
        ),
    ],
)
def test_detection_confidence_is_calibrated_by_evidence(
    metrics: FindingMetrics,
    evidence_classes: tuple[str, ...],
    quality: EvidenceQuality,
    score: float,
    signals: tuple[str, ...],
) -> None:
    detection = score_detection_confidence(
        metrics,
        evidence=EvidenceSummary.from_classes(evidence_classes),
        policy=POLICY,
    )

    assert detection.evidence_quality == quality
    assert detection.score == score
    assert detection.signals == signals
