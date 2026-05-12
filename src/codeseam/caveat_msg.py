from __future__ import annotations

EVIDENCE_CAVEATS = (
    "Do not treat findings as proof of semantic equivalence.",
    "Structural, lexical, and signature evidence require human review.",
)

SIGNATURE_CAVEATS = (
    "Signature-shape equality is not a defect by itself.",
    "Same signature shape does not imply same behavior.",
)

BROAD_UNKNOWN_SIGNATURE_CAVEATS = (
    *SIGNATURE_CAVEATS,
    "Broad UNKNOWN signature recurrence is weak evidence without a narrower blocking key.",
    "Large UNKNOWN buckets are degraded before relation scoring to avoid noisy global comparisons.",
)

BROAD_TEST_SIGNATURE_CAVEATS = (
    *SIGNATURE_CAVEATS,
    "Large test-only signature families are summarized before relation scoring.",
    "This avoids noisy test/source and test/test comparisons in broad clusters.",
    "Repeated test shapes can still be useful.",
    "Broad assertion or fixture patterns need narrower evidence.",
)

ADAPTER_WRAPPER_SIGNATURE_CAVEATS = (
    "Argument-normalization wrappers are typed composition signals, not equivalence proofs.",
    "The transform must preserve the intended domain contract before delegating.",
)

POLICY_CONSTANT_CAVEATS = (
    "Identical policy literals are maintainability signals, not proof of runtime bugs.",
    "Centralizing policy literals still requires a clear ownership boundary.",
)

ANALOGOUS_SIGNATURE_CAVEATS = (
    *SIGNATURE_CAVEATS,
    "Cross-language shape similarity is an observation, not an extraction recommendation.",
)

__all__ = [
    "ADAPTER_WRAPPER_SIGNATURE_CAVEATS",
    "ANALOGOUS_SIGNATURE_CAVEATS",
    "BROAD_TEST_SIGNATURE_CAVEATS",
    "BROAD_UNKNOWN_SIGNATURE_CAVEATS",
    "EVIDENCE_CAVEATS",
    "POLICY_CONSTANT_CAVEATS",
    "SIGNATURE_CAVEATS",
]
