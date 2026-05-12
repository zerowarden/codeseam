from __future__ import annotations

from math import prod


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def ramp(value: float, *, low: float, high: float) -> float:
    """Map a raw value onto [0, 1] using explicit low/high scoring anchors."""

    if high <= low:
        return 1.0 if value >= high else 0.0
    return clamp01((value - low) / (high - low))


def ramp_count(value: int, *, starts_at: int, high_at: int) -> float:
    """Inclusive count ramp where the first meaningful count is non-zero."""

    if value < starts_at:
        return 0.0
    return ramp(float(value), low=float(starts_at - 1), high=float(high_at))


def inverse_ramp(value: float, *, low: float, high: float) -> float:
    """Return high scores for low raw values and low scores for high values."""

    return 1.0 - ramp(value, low=low, high=high)


def combine_product(*scores: float) -> float:
    """Combine required dimensions so one weak dimension lowers the result."""

    return clamp01(prod(clamp01(score) for score in scores))


def noisy_or(*scores: float) -> float:
    """Combine optional scope signals without unbounded additive accretion."""

    return clamp01(1.0 - prod(1.0 - clamp01(score) for score in scores))


__all__ = [
    "clamp01",
    "combine_product",
    "inverse_ramp",
    "noisy_or",
    "ramp",
    "ramp_count",
]
