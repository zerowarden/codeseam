"""The labelled benchmark must not regress (scores and baseline: tests/benchmark.py)."""

from __future__ import annotations

import json
import tomllib

import benchmark
import pytest
from benchmark import BASELINE, evaluate, regressions

from codeseam.analysis import AssessmentPolicy

STABLE = {"warm_matches_cold": True}
HIGH_HOLE_COUNT_OVERRIDE = 5
RECOMMENDED_OVERRIDE = 0.5


@pytest.mark.integration
def test_benchmark_has_no_regressions() -> None:
    assert regressions(evaluate(), json.loads(BASELINE.read_text(encoding="utf-8"))) == []


@pytest.mark.parametrize(
    ("case_id", "old", "new", "regressed"),
    [
        ("PA", "recommended_edit", "maintenance_note", True),  # positive dropped
        ("PB1", "none", "recommended_edit", False),  # positive improved
        ("PE1a", "none", "recommended_edit", True),  # negative recommended
        ("PE1a", "none", "maintenance_note", False),  # cautious tier is tolerated
        ("PE1a", "maintenance_note", "observation", False),  # negative demoted
    ],
)
def test_regressions_compare_case_tiers_by_direction(
    case_id: str,
    old: str,
    new: str,
    regressed: bool,
) -> None:
    baseline = {"cases": {case_id: old}, "recommended_precision": 1.0, "stability": STABLE}
    report = {"cases": {case_id: new}, "recommended_precision": 1.0, "stability": STABLE}

    assert bool(regressions(report, baseline)) is regressed


def test_regressions_flag_precision_drops_and_instability() -> None:
    baseline = {"cases": {}, "recommended_precision": 1.0, "stability": STABLE}
    report = {"cases": {}, "recommended_precision": 0.5, "stability": {"warm_matches_cold": False}}

    assert regressions(report, baseline) == [
        "recommended precision: 1.0 -> 0.5",
        "unstable: warm_matches_cold",
    ]


def test_benchmark_overrides_round_trip_into_the_policy() -> None:
    overrides = dict(
        benchmark.parse_override(text)
        for text in ("fit.high_hole_count_at=5", "recommended_edit_threshold=0.5")
    )

    policy = AssessmentPolicy.from_config(tomllib.loads(benchmark._assessment_toml(overrides)))

    assert policy.fit.high_hole_count_at == HIGH_HOLE_COUNT_OVERRIDE
    assert policy.recommended_edit_threshold == RECOMMENDED_OVERRIDE
