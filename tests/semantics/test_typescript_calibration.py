from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pytest
from semantic_helpers import skip_without_typescript

from codeseam import cli
from codeseam.analysis import SemanticEvidenceIndex, SemanticEvidenceMetrics
from codeseam.cli.exit_codes import OK, THRESHOLD_BREACHED
from codeseam.semantics import (
    SemanticBudget,
    SemanticEnrichmentItem,
    SemanticEnrichmentRequest,
    SemanticEnrichmentResult,
    SemanticMode,
    SemanticProviderStatus,
    StdioSemanticProvider,
    typescript_worker_script,
)

FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "typescript_calibration"
WORKER = str(typescript_worker_script())


@pytest.mark.parametrize("fixture", ["declaration_only", "public_api_reexport"])
def test_typescript_calibration_surfaces_are_not_recommended_edits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    fixture: str,
) -> None:
    payload = _analyze_fixture(tmp_path, monkeypatch, capsys, fixture, semantic_mode="off")

    assert _recommended_targets(payload) == []


def test_typescript_calibration_auto_without_provider_does_not_promote_edits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    off = _analyze_fixture(
        tmp_path,
        monkeypatch,
        capsys,
        "public_api_reexport",
        semantic_mode="off",
    )
    auto = _analyze_fixture(
        tmp_path,
        monkeypatch,
        capsys,
        "public_api_reexport",
        semantic_mode="auto",
    )

    assert _recommended_count(auto) <= _recommended_count(off)
    assert auto["timings"]["semantics"]["status"] in {
        SemanticProviderStatus.DISABLED.value,
        SemanticProviderStatus.UNAVAILABLE.value,
    }


@pytest.mark.parametrize("trusted", [False, True])
def test_typescript_worker_runs_only_for_trusted_projects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    trusted: bool,
) -> None:
    if trusted and shutil.which("node") is None:
        pytest.skip("Node is not installed")
    payload = _analyze_fixture(
        tmp_path,
        monkeypatch,
        capsys,
        "same_shape_same_import",
        semantic_mode="project",
        trusted=trusted,
    )

    semantics = payload["timings"]["semantics"]
    assert semantics["request_count"] > 0
    if not trusted:
        assert semantics["answered_count"] == 0
        assert semantics["caveats"] == ["semantic_provider_untrusted"]
        return
    assert semantics["answered_count"] == semantics["request_count"]
    if "typescript_package_unavailable" in semantics["caveats"]:
        pytest.skip("TypeScript package is not resolvable by Node")
    assert semantics["compiler_available"] is True
    assert semantics["typechecker_enabled"] is True
    assert semantics["resolved_item_count"] > 0


def test_typescript_calibration_overloads_bind_to_implementation(
    tmp_path: Path,
) -> None:
    repo = _copy_fixture(tmp_path, "overloads")
    result = _worker_result(
        repo,
        _semantic_item("overload_string", "src/overloads.ts", 1, 1, "readValue"),
        _semantic_item("implementation", "src/overloads.ts", 3, 5, "readValue"),
    )
    skip_without_typescript(result)

    overload, implementation = result.items
    assert overload.declaration_only is True
    assert implementation.declaration_only is False
    assert overload.overload_group_id
    assert implementation.overload_group_id == overload.overload_group_id


def test_typescript_calibration_resolved_calls_distinguish_same_and_different_imports(
    tmp_path: Path,
) -> None:
    same_repo = _copy_fixture(tmp_path, "same_shape_same_import")
    same = _worker_result(
        same_repo,
        _semantic_item("left", "src/readers.ts", 3, 5, "readUser"),
        _semantic_item("right", "src/readers.ts", 7, 9, "readProject"),
    )
    skip_without_typescript(same)

    different_repo = _copy_fixture(tmp_path, "same_shape_different_imports")
    different = _worker_result(
        different_repo,
        _semantic_item("left", "src/user_reader.ts", 3, 5, "readUser"),
        _semantic_item("right", "src/project_reader.ts", 3, 5, "readProject"),
    )
    skip_without_typescript(different)

    assert _pair_semantic_metrics(same).shared_call_target_pair_count == 1
    assert _pair_semantic_metrics(different).divergent_call_target_pair_count == 1


def test_typescript_calibration_project_references_map_file_ownership(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path, "project_references")
    result = _worker_result(
        repo,
        _semantic_item("referenced", "packages/app/src/index.ts", 1, 3, "referenced"),
    )
    skip_without_typescript(result)

    assert result.status is SemanticProviderStatus.READY
    assert result.project.ownership_ambiguous is False
    assert result.items[0].ownership_ambiguous is False


def _analyze_fixture(  # noqa: PLR0913
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    fixture: str,
    *,
    semantic_mode: str,
    trusted: bool = False,
) -> dict[str, Any]:
    repo = _copy_fixture(tmp_path, fixture)
    if trusted:
        (repo / "codeseam.toml").write_text("[semantics]\ntrust_project_code = true\n")
    monkeypatch.chdir(repo)
    exit_code = cli.main(
        [
            "analyze",
            "--quiet",
            "--format",
            "json",
            "--timings",
            "--semantic-mode",
            semantic_mode,
        ]
    )
    assert exit_code in {OK, THRESHOLD_BREACHED}
    return cast(dict[str, Any], json.loads(capsys.readouterr().out))


def _worker_result(repo: Path, *items: SemanticEnrichmentItem) -> SemanticEnrichmentResult:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed")
    provider = StdioSemanticProvider((node, WORKER))
    return provider.enrich(
        SemanticEnrichmentRequest(
            request_id="request-1",
            language="TypeScript",
            mode=SemanticMode.PROJECT,
            repo_root=repo.as_posix(),
            project_cache_key="sha256:project",
            config_path=(repo / "tsconfig.json").as_posix(),
            items=items,
        ),
        SemanticBudget(request_timeout_ms=2_000),
    )


def _semantic_item(
    signature_id: str,
    relative_path: str,
    start_line: int,
    end_line: int,
    symbol_hint: str,
) -> SemanticEnrichmentItem:
    return SemanticEnrichmentItem(
        signature_id=signature_id,
        relative_path=relative_path,
        start_line=start_line,
        end_line=end_line,
        callable_kind="function",
        symbol_hint=symbol_hint,
    )


def _pair_semantic_metrics(result: object) -> SemanticEvidenceMetrics:
    return SemanticEvidenceIndex.from_run(
        _Run((cast(SemanticEnrichmentResult, result),)),
    ).metrics_for_members(
        (_Member("left"), _Member("right")),
        relation_pairs=(_Pair(_Member("left"), _Member("right")),),
    )


def _copy_fixture(tmp_path: Path, fixture: str) -> Path:
    target = tmp_path / f"{fixture}_{len(tuple(tmp_path.iterdir()))}"
    shutil.copytree(FIXTURE_ROOT / fixture, target)
    return target


def _recommended_targets(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        target
        for target in payload.get("targets", [])
        if target.get("review_tier") == "recommended_edit"
    ]


def _recommended_count(payload: dict[str, Any]) -> int:
    return int(payload.get("findings", {}).get("recommended_edit", 0))


@dataclass(frozen=True)
class _Run:
    results: tuple[SemanticEnrichmentResult, ...]


class _Member:
    def __init__(self, signature_id: str) -> None:
        self.signature_id = signature_id


class _Pair:
    def __init__(self, left: _Member, right: _Member) -> None:
        self.left = left
        self.right = right
