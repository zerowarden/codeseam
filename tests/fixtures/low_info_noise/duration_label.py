from __future__ import annotations


def _duration_label(seconds: object) -> str:
    value = float(seconds) if isinstance(seconds, int | float) else 0.0
    if value < SECONDS_PER_MINUTE:
        return f"{value:.3f} seconds"
    count = max(1, round(value / SECONDS_PER_MINUTE))
    unit = "minute" if count == 1 else "minutes"
    return f"{count} {unit}"
