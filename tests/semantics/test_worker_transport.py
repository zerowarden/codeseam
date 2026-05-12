from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from semantic_helpers import skip_without_typescript

from codeseam.semantics import (
    SemanticBudget,
    SemanticEnrichmentItem,
    SemanticEnrichmentRequest,
    SemanticEnrichmentResult,
    SemanticMode,
    SemanticProviderRequiredError,
    SemanticProviderStatus,
    StdioSemanticProvider,
    run_semantic_enrichment,
)

REQUEST_TIMEOUT_MS = 200
STDERR_LIMIT = 2_000
TYPECHECKER_FIXTURE = (
    Path(__file__).parents[1] / "fixtures" / "semantic_worker" / "typescript" / "typechecker"
)


def test_stdio_worker_provider_decodes_success_response(tmp_path: Path) -> None:
    provider = _provider(
        tmp_path,
        """
        import json
        import sys

        request = json.loads(sys.stdin.readline())
        print(json.dumps({
            "request_id": request["request_id"],
            "language": request["language"],
            "mode": request["mode"],
            "status": "ready",
            "provider": {
                "name": "fake_worker",
                "protocol_version": "test-protocol",
                "mode": request["mode"],
                "engine": "fake_engine",
                "engine_version": "1.0.0",
            },
            "project": {
                "project_cache_key": request["project_cache_key"],
                "config_path": request["config_path"],
                "root_file_count": 3,
                "project_reference_count": 1,
            },
            "items": [
                {
                    "signature_id": "sig_1",
                    "resolved": False,
                    "project_config_path": "/repo/tsconfig.json",
                    "ownership_ambiguous": True,
                    "caveats": ["status_only"],
                }
            ],
            "caveats": ["status_only_worker"],
        }))
        """,
    )

    result = provider.enrich(_request(), SemanticBudget(request_timeout_ms=REQUEST_TIMEOUT_MS))

    assert result.status is SemanticProviderStatus.READY
    assert result.provider.name == "fake_worker"
    assert result.items[0].signature_id == "sig_1"
    assert result.items[0].ownership_ambiguous is True
    assert result.items[0].caveats == ("status_only",)
    assert result.caveats == ("status_only_worker",)


@pytest.mark.parametrize(
    ("source", "expected_status", "expected_caveat"),
    [
        ('print("{not json")', SemanticProviderStatus.FAILED, "semantic_worker_bad_response"),
        ('print("[]")', SemanticProviderStatus.FAILED, "semantic_worker_bad_response"),
        ("", SemanticProviderStatus.FAILED, "semantic_worker_empty_response"),
        (
            'import sys; sys.stderr.write("boom"); raise SystemExit(7)',
            SemanticProviderStatus.FAILED,
            "semantic_worker_failed",
        ),
    ],
)
def test_stdio_worker_provider_reports_process_failures(
    tmp_path: Path,
    source: str,
    expected_status: SemanticProviderStatus,
    expected_caveat: str,
) -> None:
    provider = _provider(tmp_path, source)

    result = provider.enrich(_request(), SemanticBudget(request_timeout_ms=REQUEST_TIMEOUT_MS))

    assert result.status is expected_status
    assert result.fallback == "tree_sitter_only"
    assert expected_caveat in result.caveats


def test_stdio_worker_provider_reports_timeout(tmp_path: Path) -> None:
    provider = _provider(
        tmp_path,
        """
        import time
        time.sleep(2)
        """,
    )

    result = provider.enrich(_request(), SemanticBudget(request_timeout_ms=REQUEST_TIMEOUT_MS))

    assert result.status is SemanticProviderStatus.TIMED_OUT
    assert "semantic_worker_timed_out" in result.caveats


def test_stdio_worker_provider_truncates_stderr(tmp_path: Path) -> None:
    provider = _provider(
        tmp_path,
        """
        import sys
        sys.stderr.write("x" * 5000)
        raise SystemExit(1)
        """,
    )

    result = provider.enrich(_request(), SemanticBudget(request_timeout_ms=REQUEST_TIMEOUT_MS))
    stderr_caveat = next(
        item for item in result.caveats if item.startswith("semantic_worker_stderr:")
    )

    assert len(stderr_caveat) < STDERR_LIMIT


def test_auto_mode_falls_back_when_worker_is_unavailable() -> None:
    provider = StdioSemanticProvider(("definitely-missing-codeseam-semantic-worker",))

    run = run_semantic_enrichment(
        (_request(),),
        mode=SemanticMode.AUTO,
        provider=provider,
        budget=SemanticBudget(request_timeout_ms=REQUEST_TIMEOUT_MS),
    )

    assert run.status is SemanticProviderStatus.UNAVAILABLE
    assert "semantic_worker_not_found" in run.caveats


def test_required_mode_fails_when_worker_is_unavailable() -> None:
    provider = StdioSemanticProvider(("definitely-missing-codeseam-semantic-worker",))

    with pytest.raises(SemanticProviderRequiredError, match="required"):
        run_semantic_enrichment(
            (_request(mode=SemanticMode.REQUIRED),),
            mode=SemanticMode.REQUIRED,
            provider=provider,
            budget=SemanticBudget(request_timeout_ms=REQUEST_TIMEOUT_MS),
        )


def test_typescript_status_worker_maps_single_tsconfig_ownership(tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed")
    config = _write(
        tmp_path / "tsconfig.json",
        '{"files": ["src/index.ts"], "references": [{"path": "./pkg"}]}',
    )
    worker = Path("tools/semantic-worker/typescript/src/main.mjs")
    provider = StdioSemanticProvider((node, str(worker)))

    result = provider.enrich(
        _request(repo_root=tmp_path.as_posix(), config_path=config.as_posix()),
        SemanticBudget(request_timeout_ms=1_000),
    )

    assert result.status is SemanticProviderStatus.READY
    assert result.provider.name == "typescript_semantic_worker"
    assert result.items[0].signature_id == "sig_1"
    assert result.items[0].ownership_ambiguous is False


def test_typescript_worker_chooses_nearest_owner_and_reports_ambiguity(
    tmp_path: Path,
) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed")
    root_config = _write(tmp_path / "tsconfig.json", '{"include": ["packages/**/*.ts"]}')
    _write(
        tmp_path / "packages" / "app" / "tsconfig.json",
        '{"include": ["src/**/*.ts"]}',
    )
    _write(tmp_path / "packages" / "app" / "src" / "index.ts", "export const value = 1;")
    provider = StdioSemanticProvider((node, "tools/semantic-worker/typescript/src/main.mjs"))

    result = provider.enrich(
        _request(
            repo_root=tmp_path.as_posix(),
            config_path=root_config.as_posix(),
            relative_path="packages/app/src/index.ts",
        ),
        SemanticBudget(request_timeout_ms=1_000),
    )

    assert result.project.ownership_ambiguous is True
    assert result.items[0].ownership_ambiguous is True
    assert "typescript_project_ownership_ambiguous" in result.items[0].caveats


def test_typescript_worker_uses_referenced_project_for_ownership(tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed")
    root_config = _write(
        tmp_path / "tsconfig.json",
        '{"files": [], "references": [{"path": "./packages/pkg"}]}',
    )
    _write(
        tmp_path / "packages" / "pkg" / "tsconfig.json",
        '{"files": ["src/index.ts"]}',
    )
    _write(tmp_path / "packages" / "pkg" / "src" / "index.ts", "export const value = 1;")
    provider = StdioSemanticProvider((node, "tools/semantic-worker/typescript/src/main.mjs"))

    result = provider.enrich(
        _request(
            repo_root=tmp_path.as_posix(),
            config_path=root_config.as_posix(),
            relative_path="packages/pkg/src/index.ts",
        ),
        SemanticBudget(request_timeout_ms=1_000),
    )

    assert result.items[0].ownership_ambiguous is False


def test_typescript_worker_reports_missing_file_ownership(tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed")
    config = _write(tmp_path / "tsconfig.json", '{"include": ["src/**/*.ts"]}')
    _write(tmp_path / "other" / "index.ts", "export const value = 1;")
    provider = StdioSemanticProvider((node, "tools/semantic-worker/typescript/src/main.mjs"))

    result = provider.enrich(
        _request(
            repo_root=tmp_path.as_posix(),
            config_path=config.as_posix(),
            relative_path="other/index.ts",
        ),
        SemanticBudget(request_timeout_ms=1_000),
    )

    assert result.project.ownership_ambiguous is False
    assert "typescript_project_ownership_missing" in result.items[0].caveats


def test_typescript_worker_reports_pnp_without_loading_repo_code(tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed")
    config = _write(tmp_path / "tsconfig.json", '{"include": ["src/**/*.ts"]}')
    _write(tmp_path / ".pnp.cjs", "throw new Error('must not be executed');")
    _write(tmp_path / "package.json", '{"dependencies": {"typescript": "5.1.3"}}')
    _write(tmp_path / "src" / "index.ts", "export const value = 1;")
    provider = StdioSemanticProvider((node, "tools/semantic-worker/typescript/src/main.mjs"))

    result = provider.enrich(
        _request(repo_root=tmp_path.as_posix(), config_path=config.as_posix()),
        SemanticBudget(request_timeout_ms=1_000),
    )

    assert result.status is SemanticProviderStatus.READY
    assert "typescript_pnp_project_without_loader" in result.caveats


def test_typescript_worker_enriches_function_type_facts(tmp_path: Path) -> None:
    repo, config = _copy_typechecker_fixture(tmp_path)
    result = _typescript_worker_result(
        repo,
        config,
        _semantic_item("parse", start_line=1, end_line=3, symbol_hint="parseUser"),
    )
    skip_without_typescript(result)

    item = result.items[0]
    assert item.resolved is True
    assert item.symbol is not None
    assert item.symbol.name == "parseUser"
    assert item.symbol.declaration_file.endswith("src/enrich.ts")
    assert item.return_type == "number"


def test_typescript_worker_resolves_selected_call_targets(tmp_path: Path) -> None:
    repo, config = _copy_typechecker_fixture(tmp_path)
    result = _typescript_worker_result(
        repo,
        config,
        _semantic_item("caller", start_line=5, end_line=7, symbol_hint="callParse"),
    )
    skip_without_typescript(result)

    item = result.items[0]
    assert item.resolved is True
    assert item.return_type == "number"
    assert [(target.call_token, target.symbol_name) for target in item.call_targets] == [
        ("parseUser", "parseUser")
    ]


def test_typescript_worker_resolves_const_arrow_span(tmp_path: Path) -> None:
    repo, config = _copy_typechecker_fixture(tmp_path)
    result = _typescript_worker_result(
        repo,
        config,
        _semantic_item("arrow", start_line=9, end_line=9, symbol_hint="isCustomList"),
    )
    skip_without_typescript(result)

    item = result.items[0]
    assert item.resolved is True
    assert item.symbol is not None
    assert item.symbol.name == "isCustomList"
    assert item.return_type == "boolean"


def test_typescript_worker_marks_overload_declarations(tmp_path: Path) -> None:
    repo, config = _copy_typechecker_fixture(tmp_path)
    result = _typescript_worker_result(
        repo,
        config,
        _semantic_item("overload", start_line=11, end_line=11, symbol_hint="pick"),
        _semantic_item("implementation", start_line=13, end_line=15, symbol_hint="pick"),
    )
    skip_without_typescript(result)

    overload, implementation = result.items
    assert overload.resolved is True
    assert overload.declaration_only is True
    assert overload.overload_group_id
    assert implementation.resolved is True
    assert implementation.declaration_only is False
    assert implementation.overload_group_id == overload.overload_group_id


def test_typescript_worker_writes_standardized_debug_logs(tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed")
    repo, config = _copy_typechecker_fixture(tmp_path)
    payload = {
        "request_id": "request-1",
        "language": "TypeScript",
        "mode": "project",
        "repo_root": repo.as_posix(),
        "project_cache_key": "sha256:project",
        "config_path": config.as_posix(),
        "items": [
            {
                "signature_id": "parse",
                "relative_path": "src/enrich.ts",
                "start_line": 1,
                "end_line": 3,
                "callable_kind": "function",
                "symbol_hint": "parseUser",
            }
        ],
    }
    completed = subprocess.run(
        [node, "tools/semantic-worker/typescript/src/main.mjs"],
        input=json.dumps(payload) + "\n",
        text=True,
        capture_output=True,
        check=False,
        timeout=2,
        env={**os.environ, "CODESEAM_SEMANTIC_WORKER_LOG": "debug"},
    )

    assert completed.returncode == 0
    assert json.loads(completed.stdout.splitlines()[0])["status"] == "ready"
    logs = [json.loads(line) for line in completed.stderr.splitlines()]
    log = logs[0]
    assert log["component"] == "codeseam.typescript_worker"
    assert log["level"] == "debug"
    assert log["event"] == "request_received"
    response_log = next(item for item in logs if item.get("event") == "response_ready")
    assert response_log["engine"] == "node"
    assert response_log["engine_version"].startswith("v")


def _provider(tmp_path: Path, source: str) -> StdioSemanticProvider:
    script = tmp_path / "worker.py"
    script.write_text(textwrap.dedent(source).strip())
    return StdioSemanticProvider((sys.executable, script.as_posix()))


def _request(
    *,
    mode: SemanticMode = SemanticMode.AUTO,
    repo_root: str = "/repo",
    config_path: str = "/repo/tsconfig.json",
    relative_path: str = "src/index.ts",
) -> SemanticEnrichmentRequest:
    return SemanticEnrichmentRequest(
        request_id="request-1",
        language="TypeScript",
        mode=mode,
        repo_root=repo_root,
        project_cache_key="sha256:project",
        config_path=config_path,
        items=(
            SemanticEnrichmentItem(
                signature_id="sig_1",
                relative_path=relative_path,
                start_line=1,
                end_line=5,
                callable_kind="function",
                symbol_hint="run",
            ),
        ),
    )


def _copy_typechecker_fixture(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    shutil.copytree(TYPECHECKER_FIXTURE, repo)
    return repo, repo / "tsconfig.json"


def _typescript_worker_result(
    repo: Path,
    config: Path,
    *items: SemanticEnrichmentItem,
) -> SemanticEnrichmentResult:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed")
    provider = StdioSemanticProvider((node, "tools/semantic-worker/typescript/src/main.mjs"))
    return provider.enrich(
        SemanticEnrichmentRequest(
            request_id="request-1",
            language="TypeScript",
            mode=SemanticMode.PROJECT,
            repo_root=repo.as_posix(),
            project_cache_key="sha256:project",
            config_path=config.as_posix(),
            items=items,
        ),
        SemanticBudget(request_timeout_ms=1_500),
    )


def _semantic_item(
    signature_id: str,
    *,
    start_line: int,
    end_line: int,
    symbol_hint: str,
) -> SemanticEnrichmentItem:
    return SemanticEnrichmentItem(
        signature_id=signature_id,
        relative_path="src/enrich.ts",
        start_line=start_line,
        end_line=end_line,
        callable_kind="function",
        symbol_hint=symbol_hint,
    )


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path
