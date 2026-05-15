from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from helpers import assert_contains, target_record

from codeseam.cli import REPOSITORY_CONTEXT_ERROR

from .fixtures import CliRunner, SidecarWriter


@dataclass(frozen=True, slots=True)
class TargetSidecarCase:
    sidecar: str
    target_id: str
    records: list[dict[str, object]]
    expected: str


@dataclass(frozen=True, slots=True)
class ExplainPayloadCase:
    id: str
    target_id: str
    payload: dict[str, object]
    expected: tuple[str, ...]


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
    ids=lambda case: case.target_id,
)
def test_explain_reads_agent_sidecars(
    cli_runner: CliRunner,
    sidecar_writer: SidecarWriter,
    case: TargetSidecarCase,
) -> None:
    sidecar_writer(case.sidecar, case.records)

    output = cli_runner(["explain", case.target_id]).stdout

    assert_contains(
        output,
        [
            case.expected,
            "more: --source | --evidence | --pairs --top 3 | --json --full",
        ],
    )
    assert not output.lstrip().startswith("{")


@pytest.mark.parametrize(
    "args",
    [
        pytest.param(["--json", "--full"], id="json-full"),
        pytest.param(["--full"], id="full"),
    ],
)
def test_explain_full_outputs_full_json(
    cli_runner: CliRunner,
    sidecar_writer: SidecarWriter,
    args: list[str],
) -> None:
    target = target_record("rt_000001")
    sidecar_writer("analysis.jsonl", [target])

    result = cli_runner(["explain", "rt_000001", *args])

    assert json.loads(result.stdout) == target


def test_explain_source_shows_snippet(
    cli_runner: CliRunner,
    sidecar_writer: SidecarWriter,
    tmp_path: Path,
) -> None:
    source = tmp_path / "src" / "module.py"
    source.parent.mkdir()
    source.write_text("def build() -> str:\n    return 'ok'\n", encoding="utf-8")
    sidecar_writer("analysis.jsonl", [target_record("rt_000001")])

    output = cli_runner(["explain", "rt_000001", "--source"]).stdout

    assert_contains(output, ["Source:", "def build() -> str:"])


def test_explain_evidence_and_pairs_are_selected(
    cli_runner: CliRunner,
    sidecar_writer: SidecarWriter,
) -> None:
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
    sidecar_writer("analysis.jsonl", [target])

    output = cli_runner(["explain", "rt_000001", "--evidence", "--pairs", "--top", "1"]).stdout

    assert_contains(output, ["Evidence:", "Pairs:", "body_identical"])


@pytest.mark.parametrize(
    "case",
    [
        ExplainPayloadCase(
            id="semantic-guardrails",
            target_id="rt_000003",
            payload={
                "semantic_guardrails": {
                    "roles": ["constructor", "python_special_method"],
                    "reasons": [
                        "Semantic role cap: constructors should share setup helpers.",
                    ],
                }
            },
            expected=(
                "Semantic role guardrails:",
                "roles: constructor, python_special_method",
                "constructors should share setup helpers",
            ),
        ),
        ExplainPayloadCase(
            id="adapter-capabilities",
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
            expected=(
                "Adapter capability facts:",
                "TypeScript: syntax=tree_sitter",
                "compiler_semantics=no",
                "compiler semantics unavailable",
            ),
        ),
    ],
    ids=lambda case: case.id,
)
def test_explain_shows_payload_sections(
    cli_runner: CliRunner,
    sidecar_writer: SidecarWriter,
    case: ExplainPayloadCase,
) -> None:
    target = target_record(case.target_id)
    target.update(case.payload)
    sidecar_writer("analysis.jsonl", [target])

    output = cli_runner(["explain", case.target_id]).stdout

    assert_contains(output, case.expected)


def test_explain_missing_id_returns_repository_context_error(
    cli_runner: CliRunner,
    sidecar_writer: SidecarWriter,
) -> None:
    sidecar_writer(
        "analysis.jsonl", [{"target_id": "rt_000001", "review_tier": "recommended_edit"}]
    )

    cli_runner(["explain", "rt_missing"], expected=REPOSITORY_CONTEXT_ERROR)
