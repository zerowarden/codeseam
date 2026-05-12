from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import cast

import pytest
from helpers import (
    assert_contains,
    assert_paths_exist,
    explain_command_error,
    repo_dir,
    run_cli,
    run_cli_output,
    target_record,
    write_agent_sidecar,
)

from codeseam import cli
from codeseam.analysis import (
    AbstractionFit,
    ActionAssessment,
    ActionKind,
    AssessmentBand,
    AssessmentBreakdown,
    AssessmentGate,
    DetectionConfidence,
    EvidenceQuality,
    EvidenceStrength,
    Finding,
    FindingActionStatus,
    FindingDecision,
    FindingMetrics,
    FindingReviewVisibility,
    FindingTargetType,
    MaintenancePayoff,
    RecommendationStatus,
    ReviewTier,
    SemanticRisk,
)
from codeseam.cli import (
    CONFIG_ERROR,
    INTERRUPTED,
    OK,
    REPOSITORY_CONTEXT_ERROR,
    REVIEW_TIER_LABELS,
    render_ci_summary,
)
from codeseam.cli.models import OutputOptions
from codeseam.cli.output import render_analyze_result
from codeseam.output.pipeline import ReportArtifacts, threshold_breached
from codeseam.output.serializers.analysis import AnalysisPayloadSummary, analysis_result_payload
from codeseam.output.serializers.findings import agent_review_target_payload
from codeseam.platform import OutputPaths

EXPECTED_TARGET_TOP = 2
REVIEW_CONFIDENCE = 0.26
RECOMMENDATION_CONFIDENCE = 0.7
APP_SOURCE = "def app() -> int:\n    return 1\n"


@dataclass(frozen=True)
class TargetSidecarCase:
    sidecar: str
    target_id: str
    records: list[dict[str, object]]
    expected: str


@dataclass(frozen=True)
class ParserCase:
    args: list[str]
    attribute: str
    expected: object


@dataclass(frozen=True)
class InvalidRepoPathCase:
    path: str
    create_file: bool


@dataclass(frozen=True)
class AnalyzeOutputCase:
    payload: dict[str, object]
    expected: tuple[str, ...]
    absent: tuple[str, ...] = ()
    color: str = "never"


@dataclass(frozen=True)
class ExplainPayloadCase:
    target_id: str
    payload: dict[str, object]
    expected: list[str]


def _write_app_source(root: Path) -> None:
    source = root / "src" / "app.py"
    source.parent.mkdir(exist_ok=True)
    source.write_text(APP_SOURCE, encoding="utf-8")


def _prepare_app_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_app_source(tmp_path)


@pytest.mark.parametrize(
    "case",
    [
        ParserCase(["analyze"], "command", "analyze"),
        ParserCase(["analyze", "repo"], "path", "repo"),
        ParserCase(["analyze", "--since", "main"], "base_ref", "main"),
        ParserCase(["analyze", "--show-exclusions"], "show_exclusions", True),
        ParserCase(["analyze", "--include", "src/**/*.py"], "include", ["src/**/*.py"]),
        ParserCase(["analyze", "--exclude", "tests/**"], "exclude", ["tests/**"]),
        ParserCase(["analyze", "--explain-files"], "explain_files", True),
        ParserCase(["analyze", "--format", "json"], "format", "json"),
        ParserCase(["analyze", "--output", "out.json"], "output", "out.json"),
        ParserCase(["analyze", "--quiet"], "quiet", True),
        ParserCase(["analyze", "--verbose"], "verbose", True),
        ParserCase(["analyze", "--color", "never"], "color", "never"),
        ParserCase(["analyze", "--progress", "never"], "progress", "never"),
        ParserCase(["analyze", "--no-progress"], "no_progress", True),
        ParserCase(["analyze", "--ci"], "ci", True),
        ParserCase(["analyze", "--debug"], "debug", True),
        ParserCase(["analyze", "--timings"], "timings", True),
        ParserCase(["profile"], "command", "profile"),
        ParserCase(["profile", "--cold"], "cache_mode", "cold"),
        ParserCase(["profile", "--cache-mode", "warm"], "cache_mode", "warm"),
        ParserCase(["init"], "command", "init"),
        ParserCase(["init", "--no-ignore"], "no_ignore", True),
        ParserCase(["init", "--create-dirs"], "create_dirs", True),
        ParserCase(["explain", "rt_000001"], "command", "explain"),
        ParserCase(["explain", "rt_000001", "--json"], "json", True),
        ParserCase(["explain", "rt_000001", "--full"], "full", True),
        ParserCase(["explain", "rt_000001", "--verbose"], "verbose", True),
        ParserCase(["explain", "rt_000001", "--source"], "source", True),
        ParserCase(["explain", "rt_000001", "--evidence"], "evidence", True),
        ParserCase(["explain", "rt_000001", "--pairs"], "pairs", True),
        ParserCase(["explain", "rt_000001", "--top", "2"], "top", EXPECTED_TARGET_TOP),
        ParserCase(["cache"], "command", "cache"),
        ParserCase(["cache", "clear"], "cache_command", "clear"),
    ],
)
def test_cli_command_availability(case: ParserCase) -> None:
    parser = cli._build_parser()
    assert getattr(parser.parse_args(case.args), case.attribute) == case.expected


def test_main_handles_keyboard_interrupt(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def interrupt(args: object) -> int:
        del args
        raise KeyboardInterrupt

    main_module = import_module("codeseam.cli.main")
    monkeypatch.setattr(main_module, "analyze_command", interrupt)

    assert cli.main(["analyze"]) == INTERRUPTED
    assert "cancelled by user" in capsys.readouterr().err


def test_analyze_threshold_breach_detection() -> None:
    assert threshold_breached(_report_artifacts(recommended_edit_tier_count=1)) is True
    assert threshold_breached(_report_artifacts(recommended_edit_tier_count=0)) is False


def test_analyze_writes_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_cli(tmp_path, monkeypatch, ["analyze"])
    output_root = tmp_path / ".codeseam" / "reports"
    assert_paths_exist(
        output_root,
        [
            "manifest.json",
            "README.md",
            "agent/summary.md",
            "agent/analysis.jsonl",
            "agent/observations.jsonl",
            "agent/metrics.json",
        ],
    )
    for path in (
        "raw",
        "context",
        "functions.jsonl",
        "function_inventory_summary.json",
        "signatures.jsonl",
        "signature_clusters.json",
        "findings.jsonl",
    ):
        assert not (output_root / path).exists()


def test_analyze_prints_human_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = run_cli_output(tmp_path, monkeypatch, capsys, ["analyze"])
    assert_contains(
        output,
        [
            "Analyzed",
            "Discovered",
            "functions. Made",
            "Analysis:",
            REVIEW_TIER_LABELS[ReviewTier.RECOMMENDED_EDIT],
            REVIEW_TIER_LABELS[ReviewTier.REVIEW_CANDIDATE],
            REVIEW_TIER_LABELS[ReviewTier.TRACKING_SIGNAL],
            "observations.",
        ],
    )
    assert "total" not in output


@pytest.mark.parametrize(
    "case",
    [
        AnalyzeOutputCase(
            payload={
                "evidence_classes": [
                    "anti_unification_template",
                    "body_tree_similarity",
                ],
                "locations": [
                    {
                        "file": "src/helper.py",
                        "start_line": 10,
                        "end_line": 12,
                        "symbol": "build_helper",
                    }
                ],
            },
            expected=(
                "Top review required:",
                "review required  rt_review",
                "Reasons: Common code skeleton, similar body tree",
                "Action: Consolidate clone; maintenance payoff: medium",
                "src/helper.py:10-12::build_helper",
            ),
            absent=("1. rt_review",),
        ),
        AnalyzeOutputCase(
            payload={
                "target_id": "rt_sidecar",
                "title": "Framework hook recurrence",
                "primary_action": ActionKind.RECORD_SHARED_CONCERN,
                "refactor_value": "none",
                "visibility": "sidecar_only",
                "summary_eligible": False,
            },
            expected=(),
            absent=("Top review required:", "rt_sidecar"),
        ),
        AnalyzeOutputCase(
            payload={
                "locations": [
                    {
                        "file": "src/helper.py",
                        "start_line": 10,
                        "end_line": 12,
                        "symbol": "build_helper",
                    }
                ],
            },
            expected=("\x1b[36m", "src/helper.py:10-12", "::build_helper"),
            color="always",
        ),
    ],
)
def test_analyze_review_candidate_output_cases(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    case: AnalyzeOutputCase,
) -> None:
    payload = _analysis_payload_for_review_target(tmp_path, overrides=case.payload)
    payload["timings"] = {"elapsed_seconds": 0.01}

    render_analyze_result(payload, _output_options(color=case.color))

    output = capsys.readouterr().out
    assert_contains(output, list(case.expected))
    for fragment in case.absent:
        assert fragment not in output


def test_analyze_styles_review_tier_labels_when_enabled(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = _analysis_payload_for_review_target(tmp_path)
    targets = payload["targets"]
    assert isinstance(targets, list)
    targets.append(
        _ci_target(
            "rt_fix",
            title="Duplicate helper",
            review_tier=ReviewTier.RECOMMENDED_EDIT,
        )
    )
    payload["timings"] = {"elapsed_seconds": 0.01}

    render_analyze_result(payload, _output_options(color="always"))

    output = capsys.readouterr().out
    assert "recommended edits" in output
    assert "review required" in output
    assert "\x1b[1;31mrecommended edits" in output
    assert "\x1b[1;38;5;" in output and "review required" in output


def test_analyze_shows_top_ten_combined_review_targets(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    expected_review_output_count = 9
    payload = _analysis_payload_for_review_target(
        tmp_path,
        target_id="rt_fix",
        title="Recommended edit",
        review_tier=ReviewTier.RECOMMENDED_EDIT,
    )
    targets = payload["targets"]
    assert isinstance(targets, list)
    for index in range(12):
        targets.append(
            _ci_target(
                f"rt_review_{index}",
                title=f"Review required {index}",
                primary_action=ActionKind.RECORD_SHARED_CONCERN,
                refactor_value="low",
                review_score=1.0 - (index / 100),
            )
        )
    payload["timings"] = {"elapsed_seconds": 0.01}

    render_analyze_result(payload, _output_options())

    output = capsys.readouterr().out
    assert "recommended edits  rt_fix" in output
    for index in range(expected_review_output_count):
        assert f"review required  rt_review_{index}" in output
    assert f"review required  rt_review_{expected_review_output_count}" not in output
    assert output.count("review required  rt_review_") == expected_review_output_count


def test_analyze_payload_prefers_relation_pair_members(tmp_path: Path) -> None:
    payload = _analysis_payload_for_target(
        tmp_path,
        {
            **_ci_target("rt_clone", title="Duplicate helper"),
            "target_id": "rt_clone",
            "locations": [
                {
                    "file": "src/noise.py",
                    "start_line": 1,
                    "end_line": 1,
                    "symbol": "same_shape_noise",
                }
            ],
            "structural_relation_pairs": [
                {
                    "left": {
                        "file": "src/a.py",
                        "start_line": 10,
                        "end_line": 12,
                        "symbol": "duplicate_helper",
                    },
                    "right": {
                        "file": "src/b.py",
                        "start_line": 20,
                        "end_line": 22,
                        "symbol": "duplicate_helper",
                    },
                }
            ],
        },
    )
    targets = payload["targets"]
    assert isinstance(targets, list)
    target = targets[0]
    assert isinstance(target, dict)

    assert target["members"] == [
        {
            "path": "src/a.py",
            "start_line": 10,
            "end_line": 12,
            "symbol": "duplicate_helper",
        },
        {
            "path": "src/b.py",
            "start_line": 20,
            "end_line": 22,
            "symbol": "duplicate_helper",
        },
    ]


def test_analyze_show_exclusions_prints_default_patterns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = run_cli_output(
        tmp_path,
        monkeypatch,
        capsys,
        ["analyze", "--show-exclusions", "--color", "never"],
    )
    assert_contains(output, ["Default exclusions:", "- node_modules/**"])


def test_analyze_explain_files_summarizes_skipped_groups(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_app_source(tmp_path)
    (tmp_path / "src" / "ignored.py").write_text(
        "def ignored() -> int:\n    return 1\n",
        encoding="utf-8",
    )
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "pkg" / "index.js").write_text("function x() {}", encoding="utf-8")

    output = run_cli_output(
        tmp_path,
        monkeypatch,
        capsys,
        [
            "analyze",
            "--explain-files",
            "--include",
            "src/*.py",
            "--exclude",
            "src/ignored.py",
            "--color",
            "never",
        ],
    )
    assert_contains(
        output,
        [
            "Analysed: 1 files",
            "Skipped:",
            "Top skipped groups:",
            "- node_modules/: 1",
            "- src/: 1",
        ],
    )


def test_analyze_debug_writes_debug_bundle_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    assert cli.main(["analyze", "--debug"]) == OK
    output_root = tmp_path / ".codeseam" / "reports"
    assert_paths_exist(
        output_root,
        [
            "debug.jsonl.gz",
        ],
    )
    for path in ("raw", "context", "normalized", "evidence"):
        assert not (output_root / path).exists()


@pytest.mark.parametrize(
    "args",
    [
        ["analyze", "--repo-root", "repo"],
        ["analyze", "repo", "--quiet"],
    ],
)
def test_analyze_accepts_repo_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    args: list[str],
) -> None:
    repo = repo_dir(tmp_path)
    run_cli(tmp_path, monkeypatch, args)

    assert (repo / ".codeseam" / "reports" / "manifest.json").exists()


@pytest.mark.parametrize(
    "case",
    [
        InvalidRepoPathCase("missing", create_file=False),
        InvalidRepoPathCase("repo.txt", create_file=True),
    ],
    ids=lambda case: case.path,
)
@pytest.mark.parametrize("repo_arg_style", ["positional", "option"])
def test_analyze_invalid_repo_path_returns_repository_context_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: InvalidRepoPathCase,
    repo_arg_style: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    repo_path = tmp_path / case.path
    if case.create_file:
        repo_path.write_text("not a directory", encoding="utf-8")

    args = (
        ["analyze", case.path]
        if repo_arg_style == "positional"
        else ["analyze", "--repo-root", case.path]
    )
    assert cli.main(args) == REPOSITORY_CONTEXT_ERROR
    assert repo_path.is_dir() is False
    assert repo_path.exists() is case.create_file


def test_analyze_json_format_outputs_machine_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = run_cli_output(
        tmp_path,
        monkeypatch,
        capsys,
        ["analyze", "--format", "json", "--target-limit", "1", "--timings"],
    )
    payload = json.loads(output)
    assert payload["schema_version"] == "1.0"
    assert payload["codeseam_version"] == "0.1.0"
    assert payload["summary"]["files_analysed"] >= 0
    assert payload["summary"]["files_skipped"] >= 0
    assert payload["summary"]["functions_seen"] >= 0
    assert "findings" in payload
    assert payload["target_limit"] == 1
    assert "targets" in payload
    assert "timings" in payload
    assert payload["timings"]["cache"]["schema_version"] == "codeseam.cache_run_stats.v1"
    assert "namespaces" in payload["timings"]["cache"]


def test_analyze_ci_outputs_compact_summary_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    assert cli.main(["analyze", "--ci"]) == OK

    output = capsys.readouterr()
    assert output.err == ""
    assert_contains(
        output.out,
        [
            "Analysis completed.",
            "Files analysed:",
            "Files skipped:",
            "Analysis:",
            f"{REVIEW_TIER_LABELS[ReviewTier.RECOMMENDED_EDIT]}: 0",
            REVIEW_TIER_LABELS[ReviewTier.REVIEW_CANDIDATE],
            REVIEW_TIER_LABELS[ReviewTier.TRACKING_SIGNAL],
            REVIEW_TIER_LABELS[ReviewTier.OBSERVATION],
            "CI surface:",
            "No failing targets surfaced.",
            "Full results kept in artifacts:",
            "- .codeseam/reports/ci/codeseam-report.json",
            "- .codeseam/reports/ci/codeseam-report.sarif",
            "- .codeseam/reports/ci/codeseam-summary.md",
        ],
    )


def test_ci_summary_lists_failing_recommended_edits() -> None:
    output = _ci_summary(
        [
            _ci_target(
                "rt_low",
                confidence=0.99,
                review_score=0.1,
                title="High confidence but lower score",
            ),
            _ci_target(
                "rt_high",
                confidence=0.5,
                review_score=0.8,
                title="Higher review score",
                members=[_ci_member("src/high.py", 10, 12, "\nhigh")],
            ),
            _ci_target(
                "rt_fix",
                review_tier=ReviewTier.RECOMMENDED_EDIT,
                confidence=0.95,
                review_score=0.2,
                title="Recommended edit",
                members=[_ci_member("src/fix.py", 10, 12, "fix")],
            ),
            _ci_target(
                "rt_not_summary",
                confidence=1.0,
                title="Not summary eligible",
                summary_eligible=False,
            ),
            _ci_target(
                "rt_low_value",
                confidence=1.0,
                title="Low-value low-refactorability",
                refactor_value="low",
                refactorability_score=0.9,
            ),
        ],
    )

    assert_contains(
        output,
        [
            "Failing targets:",
            "rt_fix",
            "Reason: Review supporting evidence",
            "Action: Consolidate clone",
            "Members:",
            "   - src/fix.py:10-12 fix",
        ],
    )
    assert "Scores:" not in output


def test_analysis_payload_confidence_is_review_confidence(tmp_path: Path) -> None:
    payload = _analysis_payload_for_target(
        tmp_path,
        {
            "target_id": "rt_confidence",
            "title": "Confidence semantics",
            "review_tier": ReviewTier.REVIEW_CANDIDATE,
            "detection_confidence": REVIEW_CONFIDENCE,
            "recommendation_confidence": RECOMMENDATION_CONFIDENCE,
            "locations": [],
        },
    )

    targets = payload["targets"]
    assert isinstance(targets, list)
    target = targets[0]
    assert isinstance(target, dict)
    assert target["confidence"] == REVIEW_CONFIDENCE
    assert target["recommendation_confidence"] == RECOMMENDATION_CONFIDENCE
    assert target["reason"] == ""
    assert "assessment_scores" in target


def test_agent_analysis_payload_is_lean_and_uses_failed_gates() -> None:
    payload = agent_review_target_payload(
        _agent_payload_fixture(
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


def _agent_payload_fixture(
    *,
    semantic_risk: AssessmentBand,
    failed: tuple[AssessmentGate, ...],
) -> Finding:
    decision = FindingDecision(
        review_tier=ReviewTier.TRACKING_SIGNAL,
        review_score=0.0,
        action_status=FindingActionStatus.RECORD_SHARED_CONCERN,
        primary_action=ActionKind.RECORD_SHARED_CONCERN,
        evidence_strength=EvidenceStrength.STRONG,
        relatedness_score=0.9,
        refactorability_score=0.8,
        abstraction_cost_score=0.7,
        risk_score=0.0,
        confidence=0.6,
        evidence_classes=(),
        rationale=(),
    )
    return Finding(
        target_type=FindingTargetType.SIGNATURE_SHAPE,
        title="Failed gate fixture",
        review_tier=ReviewTier.TRACKING_SIGNAL,
        review_score=0.0,
        action_status=FindingActionStatus.RECORD_SHARED_CONCERN,
        primary_action=ActionKind.RECORD_SHARED_CONCERN,
        visibility=FindingReviewVisibility.GROUPED,
        summary_eligible=True,
        evidence_strength=EvidenceStrength.STRONG,
        relatedness_score=0.9,
        refactorability_score=0.8,
        abstraction_cost_score=0.7,
        risk_score=0.0,
        evidence_classes=(),
        decision=decision,
        severity="info",
        confidence=0.6,
        detection_confidence=0.6,
        recommendation_confidence=0.4,
        score_model="test",
        score_interpretation="test",
        assessment=AssessmentBreakdown(
            detection_confidence=DetectionConfidence(
                score=0.6,
                evidence_quality=EvidenceQuality.STRUCTURAL,
            ),
            abstraction_fit=AbstractionFit(
                score=0.2,
                band=AssessmentBand.LOW,
                cost=0.7,
            ),
            semantic_risk=SemanticRisk(score=0.7, band=semantic_risk),
            maintenance_payoff=MaintenancePayoff(score=0.4, band=AssessmentBand.LOW),
            action_recommendation=ActionAssessment(
                action_kind=ActionKind.RECORD_SHARED_CONCERN,
                status=RecommendationStatus.CAUTIOUS,
                preconditions_failed=failed,
                detection_confidence=0.6,
                abstraction_fit=0.2,
                semantic_risk=0.7,
                abstraction_cost=0.7,
                recommendation_confidence=0.4,
                recommendation_score=0.0,
            ),
        ),
        evidence=(),
        reasons=(),
        non_claims=(),
        suggested_refactor_direction="",
        risk="",
        files=(),
        locations=(),
        metrics=FindingMetrics(member_count=2),
        overlaps={},
        lifecycle={},
        target_id="rt_failed_gate",
        identity_hash="sha256:target",
    )


def test_analyze_ci_json_outputs_machine_payload_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    assert cli.main(["analyze", "--ci", "--format", "json"]) == OK

    output = capsys.readouterr()
    payload = json.loads(output.out)
    assert output.err == ""
    assert payload["schema_version"] == "codeseam.ci_report.v1"
    assert payload["ci"]["enabled"] is True
    assert "threshold_breached" not in payload["ci"]


def test_analyze_json_format_can_write_output_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "report.json"

    run_cli(tmp_path, monkeypatch, ["analyze", "--format", "json", "--output", str(output)])

    assert capsys.readouterr().out == ""
    assert json.loads(output.read_text(encoding="utf-8"))["schema_version"] == "1.0"


def test_analyze_sarif_format_is_reserved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_cli(tmp_path, monkeypatch, ["analyze", "--format", "sarif"], expected=CONFIG_ERROR)


def test_cache_clear_removes_audit_and_persistent_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_app_repo(tmp_path, monkeypatch)

    assert cli.main(["analyze", "--quiet"]) == OK
    assert (tmp_path / ".codeseam" / "reports").exists()
    assert (tmp_path / ".codeseam" / "cache").exists()

    assert cli.main(["cache", "clear"]) == OK


def test_cache_prints_stats(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _prepare_app_repo(tmp_path, monkeypatch)

    assert cli.main(["analyze", "--quiet"]) == OK
    assert cli.main(["cache"]) == OK

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "codeseam.cache_stats.v1"
    assert "entry_count" in payload
    assert payload["audit_output_exists"] is True


def test_profile_prints_profile_stats(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _prepare_app_repo(tmp_path, monkeypatch)

    assert cli.main(["profile", "--limit", "3"]) == OK

    output = capsys.readouterr().out
    assert_contains(
        output,
        [
            "analysis_seconds=",
            "profile_summary:",
            "selected_file_count=",
            "operation_features_count=",
            "top_clusters_by_enrichment_ms:",
            "Ordered by:",
        ],
    )


def test_init_materializes_default_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    assert cli.main(["init"]) == OK

    config_path = tmp_path / "codeseam.toml"
    assert config_path.exists()
    assert 'root = ".codeseam/reports"' in config_path.read_text(encoding="utf-8")
    assert (tmp_path / ".codeseamignore").exists()
    assert "Created:" in capsys.readouterr().out

    assert cli.main(["init"]) == OK

    output = capsys.readouterr().out
    assert_contains(output, ["Already existed:", "- codeseam.toml", "- .codeseamignore"])


def test_init_can_create_report_and_cache_dirs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    assert cli.main(["init", "--no-ignore", "--create-dirs"]) == OK

    assert (tmp_path / "codeseam.toml").exists()
    assert not (tmp_path / ".codeseamignore").exists()
    assert (tmp_path / ".codeseam" / "reports").is_dir()
    assert (tmp_path / ".codeseam" / "cache").is_dir()
    output = capsys.readouterr().out
    assert_contains(output, ["- .codeseam/reports", "- .codeseam/cache"])


def test_invalid_command_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["unknown"]) == CONFIG_ERROR

    output = capsys.readouterr()
    assert_contains(output.err, ["usage: codeseam", "analyze"])


@pytest.mark.parametrize(
    "case",
    [
        TargetSidecarCase(
            sidecar="analysis.jsonl",
            target_id="rt_000002",
            records=[
                {"target_id": "rt_000001", "review_tier": "recommended_edit"},
                {"target_id": "rt_000002", "review_tier": "recommended_edit"},
            ],
            expected="rt_000002 recommended_edit",
        ),
        TargetSidecarCase(
            sidecar="observations.jsonl",
            target_id="rt_obs",
            records=[{"target_id": "rt_obs", "review_tier": "observation"}],
            expected="rt_obs observation",
        ),
    ],
)
def test_target_reads_agent_sidecars(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    case: TargetSidecarCase,
) -> None:
    monkeypatch.chdir(tmp_path)
    write_agent_sidecar(tmp_path, case.sidecar, case.records)

    assert cli.main(["explain", case.target_id]) == OK

    output = capsys.readouterr().out
    assert_contains(
        output,
        [
            case.expected,
            "more: --source | --evidence | --pairs --top 3 | --json --full",
        ],
    )
    assert not output.lstrip().startswith("{")


@pytest.mark.parametrize("args", [["--json", "--full"], ["--full"]])
def test_target_full_outputs_full_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    args: list[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    target = target_record("rt_000001")
    write_agent_sidecar(tmp_path, "analysis.jsonl", [target])

    assert cli.main(["explain", "rt_000001", *args]) == OK

    assert json.loads(capsys.readouterr().out) == target


def test_target_source_shows_snippet(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "src" / "module.py"
    source.parent.mkdir()
    source.write_text("def build() -> str:\n    return 'ok'\n", encoding="utf-8")
    write_agent_sidecar(tmp_path, "analysis.jsonl", [target_record("rt_000001")])

    assert cli.main(["explain", "rt_000001", "--source"]) == OK

    output = capsys.readouterr().out
    assert_contains(output, ["Source:", "def build() -> str:"])


def test_target_evidence_and_pairs_are_selected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    target = target_record("rt_000001")
    target["structural_relation_pairs"] = [
        {
            "left": {"file": "src/a.py", "start_line": 1, "symbol": "a"},
            "right": {"file": "src/b.py", "start_line": 2, "symbol": "b"},
            "relation_kind": "body_identical",
            "relatedness_score": 1.0,
            "refactorability_score": 0.9,
            "risk_score": 0.0,
            "delta_kinds": [],
            "schema_version": "nested",
        }
    ]
    target["reasons"] = ["Multiple functions share the same normalized signature shape."]
    target["evidence_kinds"] = ["signature_shape_cluster"]
    write_agent_sidecar(tmp_path, "analysis.jsonl", [target])

    assert cli.main(["explain", "rt_000001", "--evidence", "--pairs", "--top", "1"]) == OK

    output = capsys.readouterr().out
    assert_contains(output, ["Evidence:", "Pairs:", "body_identical"])


@pytest.mark.parametrize(
    "case",
    [
        ExplainPayloadCase(
            target_id="rt_000003",
            payload={
                "semantic_guardrails": {
                    "roles": ["constructor", "python_special_method"],
                    "reasons": [
                        "Semantic role cap: constructors should share setup helpers.",
                    ],
                }
            },
            expected=[
                "Semantic role guardrails:",
                "roles: constructor, python_special_method",
                "constructors should share setup helpers",
            ],
        ),
        ExplainPayloadCase(
            target_id="rt_000004",
            payload={
                "adapter_capabilities": [
                    {
                        "language": "TypeScript",
                        "adapter_id": "treesitter_ecmascript_typescript",
                        "syntax_frontend": "tree_sitter",
                        "relation_detail": False,
                        "policy_constants": False,
                        "repo_facts": False,
                        "compiler_semantics": False,
                    }
                ]
            },
            expected=[
                "Adapter capability facts:",
                "TypeScript: syntax=tree_sitter",
                "compiler_semantics=no",
                "compiler semantics unavailable",
            ],
        ),
    ],
    ids=lambda case: case.target_id,
)
def test_target_explain_shows_payload_sections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    case: ExplainPayloadCase,
) -> None:
    assert_explain_contains_payload(
        tmp_path,
        monkeypatch,
        capsys,
        case,
    )


def assert_explain_contains_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    case: ExplainPayloadCase,
) -> None:
    monkeypatch.chdir(tmp_path)
    target = target_record(case.target_id)
    target.update(case.payload)
    write_agent_sidecar(tmp_path, "analysis.jsonl", [target])

    assert cli.main(["explain", case.target_id]) == OK
    assert_contains(capsys.readouterr().out, case.expected)


def test_target_missing_id_returns_repository_context_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    explain_command_error(
        tmp_path,
        monkeypatch,
        records=[{"target_id": "rt_000001", "review_tier": "recommended_edit"}],
        args=["explain", "rt_missing"],
        expected=REPOSITORY_CONTEXT_ERROR,
    )


def _ci_summary(targets: list[dict[str, object]]) -> str:
    recommended = sum(
        1 for target in targets if target.get("review_tier") == ReviewTier.RECOMMENDED_EDIT
    )
    review = sum(
        1 for target in targets if target.get("review_tier") == ReviewTier.REVIEW_CANDIDATE
    )
    return render_ci_summary(
        {
            "summary": {
                "files_analysed": 2,
                "files_skipped": 1,
                "functions_seen": 3,
            },
            "findings": {
                ReviewTier.RECOMMENDED_EDIT: recommended,
                ReviewTier.REVIEW_CANDIDATE: review,
                ReviewTier.TRACKING_SIGNAL: 0,
                ReviewTier.OBSERVATION: 0,
            },
            "ci": {
                "fail_on": "recommended_edit",
                "fail_scope": "all_targets",
                "baseline": None,
                "failing_targets": recommended,
                "exit_code": 1 if recommended else 0,
            },
        },
        targets,
    )


def _ci_target(
    target_id: str,
    **overrides: object,
) -> dict[str, object]:
    members = overrides.pop("members", None)
    if not isinstance(members, list):
        members = [_ci_member("src/target.py", 8, 8, target_id)]
    return {
        "id": target_id,
        "title": target_id,
        "review_tier": ReviewTier.REVIEW_CANDIDATE,
        "confidence": 0.5,
        "review_score": 0.5,
        "primary_action": ActionKind.CONSOLIDATE_CLONE,
        "refactor_value": "medium",
        "refactorability_score": 0.7,
        "visibility": "listed",
        "summary_eligible": True,
        "members": members,
        **overrides,
    }


def _ci_member(path: str, start: int, end: int, symbol: str) -> dict[str, object]:
    return {
        "path": path,
        "start_line": start,
        "end_line": end,
        "symbol": symbol,
    }


def _analysis_payload_for_target(tmp_path: Path, target: dict[str, object]) -> dict[str, object]:
    return analysis_result_payload(
        paths=OutputPaths(tmp_path),
        summary=AnalysisPayloadSummary(
            files_analysed=1,
            files_skipped=0,
            functions_seen=1,
        ),
        report_artifacts=ReportArtifacts(
            findings=[],
            analysis_targets=[target],
            observations=[],
            debug_targets=[target],
            report={},
            agent_summary="",
            agent_metrics={"recommended_edit_count": 0},
            meta_readme="",
        ),
        timings={},
    )


def _analysis_payload_for_review_target(
    tmp_path: Path,
    *,
    target_id: str = "rt_review",
    title: str = "Similar helper shape",
    overrides: dict[str, object] | None = None,
    **extra: object,
) -> dict[str, object]:
    target_overrides = dict(overrides or {})
    target_overrides.update(extra)
    target_id = str(target_overrides.pop("target_id", target_id))
    title = str(target_overrides.pop("title", title))
    target = {
        **_ci_target(target_id, title=title),
        "target_id": target_id,
        "assessment": {"maintenance_payoff": {"band": "medium"}},
        **target_overrides,
    }
    return _analysis_payload_for_target(tmp_path, target)


def _output_options(*, color: str = "never") -> OutputOptions:
    return OutputOptions(
        output_format=None,
        output=None,
        quiet=False,
        verbose=False,
        color=color,
        progress="never",
        timings=False,
        target_limit=50,
        ci=False,
    )


def _report_artifacts(*, recommended_edit_tier_count: int) -> ReportArtifacts:
    return ReportArtifacts(
        findings=[],
        analysis_targets=[],
        observations=[],
        debug_targets=[],
        report={},
        agent_summary="",
        agent_metrics={"recommended_edit_tier_count": recommended_edit_tier_count},
        meta_readme="",
    )
