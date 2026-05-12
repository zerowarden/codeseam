from __future__ import annotations

from codeseam.analysis import ReviewTier
from codeseam.cli.constants import REVIEW_TIER_LABELS
from codeseam.cli.repository_summary import repository_summary_lines
from codeseam.output.serializers.ci import CI_ARTIFACT_PATHS
from codeseam.output.serializers.finding_buckets import is_review_surface_target
from codeseam.output.serializers.review import targets_with_review_tiers
from codeseam.output.serializers.titles import (
    display_action_title,
    display_reason_label,
    display_sentence,
)
from codeseam.platform import (
    Json,
    as_json_object,
    json_float,
    json_int,
    plural_noun,
    plural_suffix,
    single_line,
)

CI_TOP_REVIEW_TARGET_LIMIT = 5


def render_ci_summary(payload: Json, targets: object = None) -> str:
    summary = as_json_object(payload.get("summary"))
    ci = as_json_object(payload.get("ci"))
    lines = [
        "Analysis completed.",
        "",
        "Repository:",
        *[f"  {line}" for line in repository_summary_lines(summary)],
        "",
        "Analysis:",
        _tier_line(payload, ReviewTier.RECOMMENDED_EDIT),
        _tier_line(payload, ReviewTier.REVIEW_CANDIDATE),
        _tier_line(payload, ReviewTier.TRACKING_SIGNAL),
        _tier_line(payload, ReviewTier.OBSERVATION),
        "",
        "CI:",
        f"  Fail policy: {_fail_policy(ci.get('fail_on'))}",
        f"  Fail scope: {_fail_scope(ci.get('fail_scope'))}",
        f"  Baseline: {_baseline(ci.get('baseline'))}",
        f"  Failing targets: {json_int(ci.get('failing_targets')):,}",
        f"  Exit code: {json_int(ci.get('exit_code'))}",
        "",
        "CI surface:",
        *_surface_lines(payload, targets),
    ]
    top_lines = _top_target_lines(targets)
    if top_lines:
        lines.extend(["", *top_lines])
    lines.extend(
        [
            "",
            "Artifacts:",
            *[f"- {path}" for path in CI_ARTIFACT_PATHS],
            "",
        ]
    )
    return "\n".join(lines)


def _tier_line(payload: Json, tier: ReviewTier) -> str:
    findings = payload.get("findings", {})
    count = json_int(findings.get(tier)) if isinstance(findings, dict) else 0
    return f"  {REVIEW_TIER_LABELS[tier]}: {count:,}"


def _surface_lines(payload: Json, targets: object) -> list[str]:
    findings = payload.get("findings", {})
    review_required = 0
    tracking = 0
    observations = 0
    if isinstance(findings, dict):
        review_required = json_int(findings.get(ReviewTier.REVIEW_CANDIDATE))
        tracking = json_int(findings.get(ReviewTier.TRACKING_SIGNAL))
        observations = json_int(findings.get(ReviewTier.OBSERVATION))
    failing = len(_surface_targets(targets))
    if not failing:
        return [
            "  No failing targets surfaced.",
            "  Full results kept in artifacts: "
            f"{review_required:,} review required, "
            f"{tracking:,} tracking signal"
            f"{plural_suffix(tracking)}, "
            f"{observations:,} observation{plural_suffix(observations)}.",
        ]
    listed = min(failing, CI_TOP_REVIEW_TARGET_LIMIT)
    return [
        f"  Listed below: {listed:,} {plural_noun(listed, 'failing target')}",
        "  Full results kept in artifacts: "
        f"{review_required:,} review required, "
        f"{tracking:,} tracking signal"
        f"{plural_suffix(tracking)}, "
        f"{observations:,} observation{plural_suffix(observations)}.",
    ]


def _top_target_lines(targets: object) -> list[str]:
    top_targets = _top_targets(targets)
    if not top_targets:
        return []
    heading = "Failing targets:"
    lines = [heading]
    for index, target in enumerate(top_targets, start=1):
        target_id = str(target.get("id", ""))
        lines.extend(
            [
                f"{index}. {target_id}  {target.get('title', '')}",
                *_shape_line(target),
                f"   {display_reason_label(target)}: "
                f"{display_sentence(target.get('reason') or 'review supporting evidence')}",
                f"   Action: {display_action_title(target.get('primary_action') or 'observe')}",
                "   Members:",
                *_member_lines(target.get("members")),
                "",
            ]
        )
    return lines[:-1] if lines[-1] == "" else lines


def _top_targets(targets: object) -> list[Json]:
    return _surface_targets(targets)[:CI_TOP_REVIEW_TARGET_LIMIT]


def _surface_targets(targets: object) -> list[Json]:
    review_targets = [
        target
        for target in targets_with_review_tiers(targets, {ReviewTier.RECOMMENDED_EDIT})
        if target.get("summary_eligible") is True and is_review_surface_target(target)
    ]
    return sorted(review_targets, key=_target_key)


def _target_key(target: Json) -> tuple[int, float, float, float, str]:
    recommended_rank = 0 if target.get("review_tier") == ReviewTier.RECOMMENDED_EDIT else 1
    return (
        recommended_rank,
        -json_float(target.get("review_score")),
        -_action_score(target),
        -json_float(target.get("confidence")),
        str(target.get("id", "")),
    )


def _member_lines(members: object) -> list[str]:
    if not isinstance(members, list):
        return []
    lines = []
    for member in members:
        if not isinstance(member, dict):
            continue
        lines.append(f"   - {_member_line(member)}")
    return lines


def _shape_line(target: Json) -> list[str]:
    shape = single_line(target.get("shape"))
    return [f"   Shape: {shape}"] if shape else []


def _member_line(member: Json) -> str:
    path = single_line(member.get("path"))
    start = json_int(member.get("start_line"))
    end = json_int(member.get("end_line"))
    symbol = single_line(member.get("symbol"))
    location = f"{path}:{start}" if start == end or not end else f"{path}:{start}-{end}"
    return f"{location} {symbol}".strip()


def _fail_policy(value: object) -> str:
    return "fail on recommended edits" if value == "recommended_edit" else str(value or "")


def _fail_scope(value: object) -> str:
    return "all targets" if value == "all_targets" else str(value or "")


def _baseline(value: object) -> str:
    return str(value) if value else "none"


def _action_score(target: Json) -> float:
    score = target.get("action_score")
    if isinstance(score, int | float):
        return float(score)
    assessment = target.get("assessment_scores", {})
    if not isinstance(assessment, dict):
        return 0.0
    recommendation = assessment.get("action_recommendation", {})
    if not isinstance(recommendation, dict):
        return 0.0
    return json_float(recommendation.get("score"))


__all__ = ["render_ci_summary"]
