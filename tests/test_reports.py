from __future__ import annotations

from codeseam.analysis import (
    ActionKind,
    FindingActionStatus,
)
from codeseam.output.reports.documents import build_metrics, render_agent_summary
from codeseam.platform import Json

PRIMARY_ACTION_MEMBER_LINES = 2
TOTAL_RECOMMENDED_EDIT_TIER_COUNT = 2
VISIBLE_RECOMMENDED_EDIT_COUNT = 1


def test_agent_summary_includes_agent_visible_review_targets() -> None:
    targets = [
        _full_target(f"rt_{index:06d}", "recommended_edit", f"src/{index}.py")
        for index in range(1, 13)
    ]
    metrics: Json = {
        "internal_finding_count": 0,
        "analysis_target_count": len(targets),
        "observation_count": 0,
        "recommended_edit_count": len(targets),
    }

    markdown = render_agent_summary(_report_for(targets), {"targets": targets}, metrics)

    assert "`rt_000012`" in markdown
    assert "Do not read full JSONL sidecars by default" in markdown
    assert "Listed targets: 12\n## Agent-Visible Review Targets" in markdown
    assert "Evidence:" in markdown
    assert "`strength" in markdown
    assert "Scores:" in markdown
    assert "`relatedness" in markdown
    assert "Inspect: `codeseam explain rt_000001`" in markdown
    assert "visibility: `agent_summary`" in markdown
    assert markdown.count("Suggested action") == len(targets)


def test_agent_summary_uses_visibility_not_priority() -> None:
    visible = _full_target("rt_000001", "recommended_edit", "src/visible.py")
    hidden = _full_target("rt_000002", "recommended_edit", "src/hidden.py")
    hidden["visibility"] = "sidecar_only"
    hidden["summary_eligible"] = False
    targets = [visible, hidden]

    markdown = render_agent_summary(
        _report_for(targets),
        {"targets": targets},
        {
            "internal_finding_count": 0,
            "analysis_target_count": 2,
            "observation_count": 0,
            "recommended_edit_count": 1,
        },
    )

    assert "`rt_000001`" in markdown
    assert markdown.count("Suggested action") == 1


def test_agent_summary_hides_low_value_low_refactorability_targets() -> None:
    visible = _full_target("rt_000001", "recommended_edit", "src/visible.py")
    weak = _full_target("rt_000002", "maintenance_note", "src/weak.py")
    weak["refactor_value"] = "low"
    weak["refactorability_score"] = 0.2
    targets = [visible, weak]

    markdown = render_agent_summary(
        _report_for(targets),
        {"targets": targets},
        {
            "internal_finding_count": 0,
            "analysis_target_count": 2,
            "observation_count": 0,
            "recommended_edit_count": 1,
        },
    )

    assert "`rt_000001`" in markdown
    assert markdown.count("Suggested action") == 1


def test_build_metrics_counts_recommended_edits_from_agent_visible_targets() -> None:
    visible = _full_target("rt_000001", "recommended_edit", "src/visible.py")
    visible["action_status"] = FindingActionStatus.RECOMMENDED_EDIT
    hidden = _full_target("rt_000002", "recommended_edit", "src/hidden.py")
    hidden["action_status"] = FindingActionStatus.RECOMMENDED_EDIT
    hidden["visibility"] = "sidecar_only"
    hidden["summary_eligible"] = False

    metrics = build_metrics(
        {"summary": {}, "artifact_index": {}},
        [visible, hidden],
        [],
        [],
    )

    assert metrics["agent_visible_target_count"] == VISIBLE_RECOMMENDED_EDIT_COUNT
    assert metrics["recommended_edit_tier_count"] == TOTAL_RECOMMENDED_EDIT_TIER_COUNT
    assert metrics["recommended_edit_count"] == VISIBLE_RECOMMENDED_EDIT_COUNT


def test_agent_summary_prefers_primary_action_members() -> None:
    target = _full_target("rt_000001", "recommended_edit", "src/noisy.py")
    target["locations"] = [
        {
            "file": "src/noisy.py",
            "start_line": 1,
            "end_line": 2,
            "symbol": "noise",
        }
    ]
    target["refactor_action_candidates"] = [
        {
            "kind": ActionKind.CONSOLIDATE_CLONE,
            "confidence": 0.97,
            "status": "recommended",
            "applies_to": [
                {
                    "file": "src/codeseam/output/target_buckets.py",
                    "start_line": 17,
                    "end_line": 18,
                    "symbol": "analysis_targets",
                },
                {
                    "file": "src/codeseam/output/target_buckets.py",
                    "start_line": 21,
                    "end_line": 22,
                    "symbol": "observation_targets",
                },
            ],
        }
    ]

    markdown = render_agent_summary(
        _report_for([target]),
        {"targets": [target]},
        {
            "internal_finding_count": 0,
            "analysis_target_count": 1,
            "observation_count": 0,
            "recommended_edit_count": 1,
        },
    )

    assert "target_buckets.py:17-18 analysis_targets" in markdown
    assert "target_buckets.py:21-22 observation_targets" in markdown
    assert markdown.count("target_buckets.py:") == PRIMARY_ACTION_MEMBER_LINES


def test_agent_summary_target_listing_can_be_capped() -> None:
    targets = [
        _full_target(f"rt_{index:06d}", "recommended_edit", f"src/{index}.py")
        for index in range(1, 6)
    ]
    metrics: Json = {
        "internal_finding_count": 0,
        "analysis_target_count": len(targets),
        "observation_count": 0,
        "recommended_edit_count": len(targets),
    }

    markdown = render_agent_summary(
        _report_for(targets),
        {"targets": targets},
        metrics,
        max_targets=2,
    )

    assert "`rt_000001`" in markdown
    assert "`rt_000002`" in markdown
    assert "Listed targets: 2; omitted by config: 3" in markdown


def _report_for(targets: list[Json]) -> Json:
    return {
        "run": {"profile": "test", "status": {"ok": True}},
        "summary": {
            "finding_count": 0,
            "review_target_count": len(targets),
            "targets_by_review_tier": {str(target["review_tier"]): 1 for target in targets},
        },
    }


def _full_target(target_id: str, review_tier: str, *files: str) -> Json:
    return {
        "schema_version": "codeseam.review_target.v1",
        "target_id": target_id,
        "target_type": "file_module_concern",
        "title": "Repeated shape",
        "review_tier": review_tier,
        "review_score": 0.8,
        "visibility": "agent_summary",
        "summary_eligible": True,
        "evidence_strength": "strong",
        "relatedness_score": 0.8,
        "refactorability_score": 0.7,
        "abstraction_cost_score": 0.2,
        "risk_score": 0.1,
        "evidence_classes": ["body_tree_similarity"],
        "decision": {
            "review_tier": review_tier,
            "review_score": 0.8,
            "evidence_strength": "strong",
            "relatedness_score": 0.8,
            "refactorability_score": 0.7,
            "abstraction_cost_score": 0.2,
            "risk_score": 0.1,
            "confidence": 0.8,
            "evidence_classes": ["body_tree_similarity"],
            "rationale": ["fixture"],
        },
        "severity": "medium",
        "confidence": 0.8,
        "assessment": {},
        "evidence": [{"kind": "signature_cluster", "id": "sigcl_000001"}],
        "reasons": ["Review repeated evidence before editing."],
        "non_claims": ["Evidence is not proof."],
        "suggested_refactor_direction": "inspect",
        "risk": "medium",
        "files": list(files),
        "locations": [],
        "metrics": {},
        "overlaps": {},
        "lifecycle": {"state": "new", "suppressed": False},
        "refactor_action_candidates": [{"kind": ActionKind.CONSOLIDATE_CLONE, "confidence": 0.8}],
        "refactor_action_summary": {
            "primary_action": ActionKind.CONSOLIDATE_CLONE,
            "secondary_action": "",
            "not_recommended": [],
            "primary_scope": "consolidate clone pairs with concrete body evidence",
        },
    }
