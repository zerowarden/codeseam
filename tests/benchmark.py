"""Score codeseam against the labelled corpus in tests/fixtures/benchmark.

    uv run python tests/benchmark.py            # print scores, exit 1 on regression
    uv run python tests/benchmark.py --update   # accept current scores as the baseline
    uv run python tests/benchmark.py --set fit.high_hole_count_at=4        # score an override
    uv run python tests/benchmark.py --sweep recommended_edit_threshold=0.3,0.42,0.5
    uv run python tests/benchmark.py --sensitivity   # which constants the corpus constrains

Overrides are `[assessment]` settings (see AssessmentPolicy); they are written to
the corpus copy's codeseam.toml, so the real configuration path is exercised.

The baseline records the review tier every labelled case reaches. A change
regresses when a positive drops a tier, a negative becomes a recommended edit
(the answer key tolerates cautious lower tiers for negatives), recommended
precision falls, or results stop being stable across caching and an unrelated
file insertion.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import tomllib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path
from typing import Any, cast

from codeseam import cli
from codeseam.analysis import AssessmentPolicy

CORPUS = Path(__file__).parent / "fixtures" / "benchmark"
BASELINE = CORPUS / "baseline.json"
TIERS = ("none", "observation", "maintenance_note", "review_candidate", "recommended_edit")
RECOMMENDED = "recommended_edit"
AGENT_ARTIFACTS = ("analysis.jsonl", "observations.jsonl", "metrics.json", "summary.md")
# Ordinary untyped helpers that share signature buckets with the corpus, so an
# insertion genuinely exercises clustering instead of landing in an empty bucket.
UNRELATED_FILES = {
    "py/zz_unrelated.py": (
        "def describe_batch(batch):\n"
        "    size = len(batch)\n"
        "    return f'{size} items'\n\n\n"
        "def merge_tags(left, right):\n"
        "    return sorted(set(left) | set(right))\n"
    ),
    "ts/src/zz_unrelated.ts": (
        "export function describeBatch(batch: string[]): string {\n"
        "  const size = batch.length;\n"
        "  return `${size} items`;\n"
        "}\n"
    ),
}


@dataclass(frozen=True)
class Case:
    id: str
    category: str
    positive: bool
    files: frozenset[str]


@dataclass(frozen=True)
class Run:
    targets: tuple[dict[str, object], ...]
    artifacts: dict[str, str]


def load_cases() -> list[Case]:
    raw = tomllib.loads((CORPUS / "labels.toml").read_text(encoding="utf-8"))["case"]
    return [
        Case(
            id=item["id"],
            category=item["category"],
            positive=item["expect"] == "positive",
            files=frozenset(member.partition(":")[0] for member in item["members"]),
        )
        for item in raw
    ]


def evaluate(overrides: dict[str, object] | None = None) -> dict[str, object]:
    cases = load_cases()
    with tempfile.TemporaryDirectory() as tmp:
        repo = shutil.copytree(
            CORPUS,
            Path(tmp) / "corpus",
            ignore=shutil.ignore_patterns("labels.toml", "baseline.json"),
        )
        if overrides:
            (repo / "codeseam.toml").write_text(_assessment_toml(overrides), encoding="utf-8")
        cold = _analyze(repo)
        warm = _analyze(repo)
        uncached = _analyze(repo, cache=False)
        for relative, source in UNRELATED_FILES.items():
            (repo / relative).write_text(source, encoding="utf-8")
        inserted = _analyze(repo)
    tiers = case_tiers(cases, cold.targets)
    return {
        "cases": tiers,
        "recommended_precision": _recommended_precision(cases, cold.targets),
        "recall": _recall(cases, tiers),
        "negatives_surfaced": sorted(
            case.id for case in cases if not case.positive and tiers[case.id] != "none"
        ),
        "stability": {
            "warm_matches_cold": warm.artifacts == cold.artifacts,
            "uncached_matches_cold": uncached.artifacts == cold.artifacts,
            "insertion_keeps_case_tiers": case_tiers(cases, inserted.targets) == tiers,
            "insertion_keeps_recommended_ids": _recommended_ids(inserted) == _recommended_ids(cold),
        },
    }


def case_tiers(cases: list[Case], targets: tuple[dict[str, object], ...]) -> dict[str, str]:
    """Best tier each case reaches through a target confined to its files."""

    return {
        case.id: max(
            (str(t["review_tier"]) for t in targets if _files(t) <= case.files),
            key=TIERS.index,
            default="none",
        )
        for case in cases
    }


def regressions(report: dict[str, object], baseline: dict[str, object]) -> list[str]:
    cases = {case.id: case for case in load_cases()}
    found = []
    old_tiers = _str_dict(baseline["cases"])
    for case_id, tier in _str_dict(report["cases"]).items():
        old = old_tiers.get(case_id, "none")
        if cases[case_id].positive:
            regressed = TIERS.index(tier) < TIERS.index(old)
        else:
            regressed = tier == RECOMMENDED and old != RECOMMENDED
        if regressed:
            found.append(f"{case_id}: {old} -> {tier}")
    precision, previous = report["recommended_precision"], baseline["recommended_precision"]
    assert isinstance(precision, float) and isinstance(previous, float)
    if precision < previous:
        found.append(f"recommended precision: {previous} -> {precision}")
    stability = report["stability"]
    assert isinstance(stability, dict)
    found.extend(f"unstable: {name}" for name, ok in stability.items() if not ok)
    return found


def _analyze(repo: Path, *, cache: bool = True) -> Run:
    with _env("CODESEAM_CACHE_ENABLED", "true" if cache else "false"):
        assert cli.main(["analyze", str(repo), "--quiet"]) in {cli.OK, cli.THRESHOLD_BREACHED}
    agent = repo / ".codeseam" / "reports" / "agent"
    targets = tuple(
        json.loads(line)
        for name in ("analysis.jsonl", "observations.jsonl")
        for line in (agent / name).read_text(encoding="utf-8").splitlines()
    )
    return Run(
        targets=targets,
        artifacts={name: (agent / name).read_text(encoding="utf-8") for name in AGENT_ARTIFACTS},
    )


@contextmanager
def _env(name: str, value: str) -> Iterator[None]:
    previous = os.environ.get(name)
    os.environ[name] = value
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous


def _files(target: dict[str, object]) -> frozenset[str]:
    files = target.get("files")
    return frozenset(str(item) for item in files) if isinstance(files, list) else frozenset()


def _recommended_precision(cases: list[Case], targets: tuple[dict[str, object], ...]) -> float:
    recommended = [_files(t) for t in targets if t["review_tier"] == RECOMMENDED]
    positives = [case.files for case in cases if case.positive]
    hits = sum(any(files <= case for case in positives) for files in recommended)
    return round(hits / len(recommended), 4) if recommended else 1.0


def _recall(cases: list[Case], tiers: dict[str, str]) -> dict[str, str]:
    recall: dict[str, str] = {}
    for category in sorted({case.category for case in cases if case.positive}):
        members = [case for case in cases if case.positive and case.category == category]
        recommended = sum(tiers[case.id] == RECOMMENDED for case in members)
        surfaced = sum(tiers[case.id] != "none" for case in members)
        recall[category] = f"{recommended}/{len(members)} recommended, {surfaced} surfaced"
    return recall


def _recommended_ids(run: Run) -> set[str]:
    return {str(t["target_id"]) for t in run.targets if t["review_tier"] == RECOMMENDED}


def _str_dict(value: object) -> dict[str, str]:
    assert isinstance(value, dict)
    return {str(key): str(item) for key, item in value.items()}


def parse_override(text: str) -> tuple[str, object]:
    """`fit.high_hole_count_at=4` -> ("fit.high_hole_count_at", 4), values as TOML."""

    key, sep, value = text.partition("=")
    if not sep or not key:
        raise argparse.ArgumentTypeError(f"expected key=value, got {text!r}")
    return key.strip(), tomllib.loads(f"v = {value.strip()}")["v"]


def _assessment_toml(overrides: dict[str, object]) -> str:
    tables: dict[str, list[str]] = {}
    for dotted, value in overrides.items():
        group, _, name = dotted.rpartition(".")
        header = f"assessment.{group}" if group else "assessment"
        tables.setdefault(header, []).append(f"{name} = {json.dumps(value)}")
    return "".join(f"[{header}]\n" + "\n".join(lines) + "\n" for header, lines in tables.items())


def _sweep(spec: str, overrides: dict[str, object]) -> int:
    key, _, values = spec.partition("=")
    for raw in values.split(","):
        _, value = parse_override(f"{key}={raw}")
        report = evaluate({**overrides, key: value})
        tiers = _str_dict(report["cases"])
        recommended = sorted(case for case, tier in tiers.items() if tier == RECOMMENDED)
        print(
            f"{key}={raw}: precision {report['recommended_precision']} "
            f"recommended {recommended} recall {report['recall']}"
        )
    return 0


def _sensitivity() -> int:
    """Move every numeric policy constant by -30%/+30% and report corpus changes."""

    cases = load_cases()
    with tempfile.TemporaryDirectory() as tmp:
        repo = shutil.copytree(
            CORPUS,
            Path(tmp) / "corpus",
            ignore=shutil.ignore_patterns("labels.toml", "baseline.json"),
        )

        def score(overrides: dict[str, object]) -> tuple[dict[str, str], float]:
            (repo / "codeseam.toml").write_text(_assessment_toml(overrides), encoding="utf-8")
            shutil.rmtree(repo / ".codeseam", ignore_errors=True)
            targets = _analyze(repo, cache=False).targets
            return case_tiers(cases, targets), _recommended_precision(cases, targets)

        base_tiers, base_precision = score({})
        inert = []
        for name, value in _policy_constants(AssessmentPolicy()):
            moved = False
            for scaled in _perturbations(value):
                tiers, precision = score({name: scaled})
                changed = {
                    k: f"{base_tiers[k]} -> {v}" for k, v in tiers.items() if v != base_tiers[k]
                }
                if changed or precision != base_precision:
                    moved = True
                    print(f"{name} = {scaled} (default {value}): precision {precision} {changed}")
            if not moved:
                inert.append(name)
    print(f"\nUnconstrained by the corpus within 30% ({len(inert)}): {', '.join(inert)}")
    return 0


def _policy_constants(policy: object, prefix: str = "") -> Iterator[tuple[str, int | float]]:
    for item in fields(cast(Any, policy)):
        value = getattr(policy, item.name)
        if is_dataclass(value):
            yield from _policy_constants(value, f"{prefix}{item.name}.")
        elif type(value) in {int, float} and item.name != "precision":
            yield f"{prefix}{item.name}", value


def _perturbations(value: int | float) -> list[int | float]:
    if isinstance(value, float):
        return [round(value * 0.7, 4), round(value * 1.3, 4)]
    return [max(0, min(value - 1, round(value * 0.7))), max(value + 1, round(value * 1.3))]


def main() -> int:
    parser = argparse.ArgumentParser(description="Score codeseam on the labelled corpus.")
    parser.add_argument("--update", action="store_true", help="Accept current scores as baseline.")
    parser.add_argument(
        "--set",
        dest="overrides",
        action="append",
        type=parse_override,
        default=[],
        metavar="KEY=VALUE",
        help="Score with an [assessment] override (repeatable).",
    )
    parser.add_argument("--sweep", metavar="KEY=V1,V2", help="Print scores for each value.")
    parser.add_argument(
        "--sensitivity", action="store_true", help="Report which constants change the corpus."
    )
    args = parser.parse_args()
    overrides = dict(args.overrides)
    if args.update and (overrides or args.sweep):
        parser.error("--update records the defaults; drop --set/--sweep")
    try:
        AssessmentPolicy.from_config(tomllib.loads(_assessment_toml(overrides)))
    except ValueError as exc:
        parser.error(str(exc))
    if args.sensitivity:
        return _sensitivity()
    if args.sweep:
        return _sweep(args.sweep, overrides)
    report = evaluate(overrides)
    print(json.dumps(report, indent=2))
    if args.update:
        BASELINE.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"Baseline updated: {BASELINE}")
        return 0
    found = regressions(report, json.loads(BASELINE.read_text(encoding="utf-8")))
    for line in found:
        print(f"REGRESSION {line}", file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
