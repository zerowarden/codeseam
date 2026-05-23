from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from codeseam.adapters.repository.root import detect_repo_root
from codeseam.adapters.repository.scan_manifest import scan_manifest_path
from codeseam.analysis import (
    FileRecord,
    RepositoryScan,
    build_repository_facts,
    classify_path,
    repository_facts_cache_value,
    repository_facts_from_cache_value,
)
from codeseam.config import load_config
from codeseam.output.serializers.repository import file_record_payload
from codeseam.pipeline.repository import scan_repository
from codeseam.platform import OutputPaths, write_atomic

EXPECTED_TYPESCRIPT_FILE_COUNT = 2


def test_git_root_detection(tmp_path: Path) -> None:
    if shutil.which("git") is None:
        pytest.skip("git unavailable")
    repo = tmp_path / "repo"
    child = repo / "a" / "b"
    child.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)

    assert detect_repo_root(cwd=child) == repo.resolve()


def test_current_directory_fallback(tmp_path: Path) -> None:
    assert detect_repo_root(cwd=tmp_path) == tmp_path.resolve()


def test_repo_root_detection_uses_language_neutral_project_markers(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    child = repo / "packages" / "app"
    child.mkdir(parents=True)
    (repo / "package.json").write_text("{}", encoding="utf-8")

    assert detect_repo_root(cwd=child) == repo.resolve()


def test_file_selection_excludes_defaults(tmp_path: Path) -> None:
    write_atomic(tmp_path / "src" / "app.py", "x = 1\n")
    for path in [
        ".git/config",
        "node_modules/lib/index.js",
        ".venv/lib/site.py",
        "venv/lib/site.py",
        "dist/app.js",
        "build/app.js",
        "coverage/index.html",
        "fixtures/case.py",
        "tests/fixtures/case.py",
        "__fixtures__/case.ts",
        "tests/__fixtures__/case.ts",
        ".next/server.js",
        ".nuxt/server.js",
        "__pycache__/x.pyc",
        "static/app.min.js",
        "static/app.js.map",
        "generated/client.ts",
        "src/generated/client.ts",
        "src/api.generated.ts",
        ".pnp.cjs",
        ".pnp.loader.mjs",
        "poetry.lock",
        "uv.lock",
    ]:
        write_atomic(tmp_path / path, "x = 1\n")

    artifacts = _scan(tmp_path)

    assert [record.path for record in artifacts.records] == ["src/app.py"]
    assert artifacts.selected_paths == ["src/app.py"]


def test_file_selection_respects_gitignore(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    _write_files(
        tmp_path,
        {
            ".gitignore": "ignored.py\nignored_dir/\n",
            "src/app.py": "x = 1\n",
            "ignored.py": "x = 1\n",
            "ignored_dir/nested.py": "x = 1\n",
        },
    )

    artifacts = _scan(tmp_path)

    assert [record.path for record in artifacts.records] == [".gitignore", "src/app.py"]
    assert artifacts.selected_paths == ["src/app.py"]


def test_file_selection_keeps_codeseam_excludes_inside_git_repo(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    _write_files(
        tmp_path,
        {
            "src/app.py": "x = 1\n",
            "node_modules/pkg/index.js": "x = 1\n",
            ".yarn/releases/yarn.cjs": "x = 1\n",
            "dist/app.py": "x = 1\n",
        },
    )

    artifacts = _scan(tmp_path)

    assert [record.path for record in artifacts.records] == ["src/app.py"]
    assert artifacts.selected_paths == ["src/app.py"]


def test_file_selection_respects_global_gitignore(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if shutil.which("git") is None:
        pytest.skip("git unavailable")
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    global_ignore = tmp_path / "global_ignore"
    global_ignore.write_text("global_ignored.py\n", encoding="utf-8")
    global_config = tmp_path / "gitconfig"
    global_config.write_text(
        f"[core]\n\texcludesFile = {global_ignore.as_posix()}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))
    write_atomic(repo / "src" / "app.py", "x = 1\n")
    write_atomic(repo / "global_ignored.py", "x = 1\n")

    artifacts = _scan(repo)

    assert [record.path for record in artifacts.records] == ["src/app.py"]
    assert artifacts.selected_paths == ["src/app.py"]


def test_file_record_serializes_without_generic_dataclass_walk(tmp_path: Path) -> None:
    write_atomic(tmp_path / "src" / "app.py", "x = 1\n")

    [record] = _scan(tmp_path).records
    payload = file_record_payload(record)

    assert payload["path"] == "src/app.py"
    assert payload["language"] == "Python"
    assert payload["is_test"] is False


@pytest.mark.parametrize(
    ("path", "expected_role"),
    (
        ("tests/test_app.py", "test"),
        ("tests/fixtures/case.py", "fixture"),
        ("src/generated/client.py", "generated"),
        ("vendor/pkg/lib.py", "vendor"),
        (".yarn/releases/yarn.cjs", "vendor"),
        ("dist/app.js", "build_output"),
    ),
)
def test_classification_for_tests_fixtures_and_generated_paths(
    path: str,
    expected_role: str,
) -> None:
    assert classify_path(Path(path)).role == expected_role


def test_file_selection_uses_language_specific_test_patterns(tmp_path: Path) -> None:
    for path in [
        "src/conftest.py",
        "src/user.test.ts",
        "src/account.spec.tsx",
        "src/payment-test.js",
        "src/widget-spec.jsx",
        "src/app.py",
    ]:
        write_atomic(tmp_path / path, "x = 1\n")

    records = {record.path: record for record in _scan(tmp_path).records}

    assert records["src/conftest.py"].role == "test"
    assert records["src/user.test.ts"].role == "test"
    assert records["src/account.spec.tsx"].role == "test"
    assert records["src/payment-test.js"].role == "test"
    assert records["src/widget-spec.jsx"].role == "test"
    assert records["src/app.py"].role == "source"


def test_python_test_classification_uses_path_config(tmp_path: Path) -> None:
    write_atomic(
        tmp_path / "pyproject.toml",
        "[tool.pytest.ini_options]\npython_files = ['check_*.py']\ntestpaths = ['checks']\n",
    )
    for path in [
        "src/check_payment.py",
        "checks/helper.py",
        "src/app.py",
    ]:
        write_atomic(tmp_path / path, "x = 1\n")

    records = {record.path: record for record in _scan(tmp_path).records}

    assert records["src/check_payment.py"].role == "test"
    assert records["checks/helper.py"].role == "test"
    assert records["src/app.py"].role == "source"


def test_manifest_discovery_records_project_manifests(tmp_path: Path) -> None:
    write_atomic(tmp_path / "pyproject.toml", "x = 1\n")
    write_atomic(tmp_path / "package.json", "{}\n")
    write_atomic(tmp_path / "requirements-dev.txt", "pytest\n")
    write_atomic(tmp_path / "frontend" / "pnpm-lock.yaml", "lockfileVersion: 9\n")
    write_atomic(tmp_path / "frontend" / "tsconfig.build.json", "{}\n")
    write_atomic(tmp_path / "src" / "app.ts", "export const x = 1;\n")

    _scan(tmp_path)

    context_root = tmp_path / ".codeseam" / "reports" / "context"
    manifests = json.loads((context_root / "manifests.json").read_text())
    assert {"path": "pyproject.toml", "kind": "python"} in manifests["manifests"]
    assert {"path": "requirements-dev.txt", "kind": "python"} in manifests["manifests"]
    assert {"path": "package.json", "kind": "node"} in manifests["manifests"]
    assert {"path": "frontend/pnpm-lock.yaml", "kind": "node"} in manifests["manifests"]
    assert {"path": "frontend/tsconfig.build.json", "kind": "typescript_config"} in manifests[
        "manifests"
    ]
    assert not (context_root / "typescript_projects.json").exists()


def test_repo_relative_paths_and_deterministic_order(tmp_path: Path) -> None:
    write_atomic(tmp_path / "b.py", "x = 1\n")
    write_atomic(tmp_path / "a.py", "x = 1\n")

    first = _scan(tmp_path)
    second = _scan(tmp_path)

    assert [record.path for record in first.records] == ["a.py", "b.py"]
    assert [record.path for record in second.records] == ["a.py", "b.py"]
    assert all(not Path(record.path).is_absolute() for record in first.records)


def test_symlink_outside_repo_is_skipped(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside_codeseam_phase1.py"
    outside.write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "inside.py").write_text("x = 2\n", encoding="utf-8")
    (tmp_path / "linked.py").symlink_to(outside)

    artifacts = _scan(tmp_path)

    assert [record.path for record in artifacts.records] == ["inside.py"]


def test_repository_facts_preserve_scan_and_precompute_common_lookups(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "src" / "app.ts").write_text(
        "export function app() { return 1 }\n",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "app.test.ts").write_text(
        "export function testApp() { return 1 }\n",
        encoding="utf-8",
    )
    scan = _scan(tmp_path)

    facts = build_repository_facts(scan)

    assert facts.records == tuple(scan.records)
    assert facts.selected_paths == tuple(scan.selected_paths)
    assert facts.roles_by_path["src/app.ts"] == "source"
    assert facts.roles_by_path["tests/app.test.ts"] == "test"
    assert facts.languages_by_path["src/app.ts"] == "TypeScript"
    assert facts.records_by_path["src/app.ts"].path == "src/app.ts"
    assert facts.language_counts["TypeScript"] == EXPECTED_TYPESCRIPT_FILE_COUNT
    assert facts.role_counts["source"] >= 1
    assert any(manifest.kind == "node" for manifest in facts.manifests)


def test_repository_facts_cache_value_round_trips_without_json_payload(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("def app():\n    return 1\n", encoding="utf-8")
    facts = build_repository_facts(_scan(tmp_path))

    value = repository_facts_cache_value(facts)
    restored = repository_facts_from_cache_value(value)

    assert not isinstance(value, dict)
    assert restored is not None
    assert restored.records == facts.records
    assert restored.selected_paths == facts.selected_paths
    assert restored.manifests == facts.manifests
    assert restored.roles_by_path == facts.roles_by_path


def test_scan_manifest_reuses_content_hash_but_recomputes_role(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "src" / "app.py"
    write_atomic(source, "def app():\n    return 1\n")
    first = _scan(tmp_path)
    first_record = _record_by_path(first, "src/app.py")
    assert first_record.role == "source"

    write_atomic(
        tmp_path / "pyproject.toml",
        "[tool.pytest.ini_options]\ntestpaths = ['src']\n",
    )
    original_read_bytes = Path.read_bytes

    def read_bytes(path: Path) -> bytes:
        if path == source:
            raise AssertionError("scan manifest hit should not reread unchanged file bytes")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)

    second_record = _record_by_path(_scan(tmp_path), "src/app.py")
    assert second_record.content_hash == first_record.content_hash
    assert second_record.line_count == first_record.line_count
    assert second_record.role == "test"


def test_scan_manifest_rehashes_when_file_stat_changes(tmp_path: Path) -> None:
    source = tmp_path / "src" / "app.py"
    write_atomic(source, "def app():\n    return 1\n")
    first_record = _record_by_path(_scan(tmp_path), "src/app.py")

    write_atomic(source, "def app():\n    return 2\n")

    second_record = _record_by_path(_scan(tmp_path), "src/app.py")
    assert second_record.content_hash != first_record.content_hash


def test_scan_manifest_invalid_payload_degrades_to_full_scan(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    manifest_path = scan_manifest_path(config.cache_path())
    write_atomic(manifest_path, "{not json")
    write_atomic(tmp_path / "src" / "app.py", "def app():\n    return 1\n")

    record = _record_by_path(_scan(tmp_path), "src/app.py")

    assert record.content_hash.startswith("sha256:")
    assert "schema_version" in manifest_path.read_text(encoding="utf-8")


def _scan(root: Path) -> RepositoryScan:
    config = load_config(root)
    paths = OutputPaths(config.path("output", "root"))
    paths.ensure_audit()
    return scan_repository(config, paths, write_artifacts=True)


def _record_by_path(scan: RepositoryScan, path: str) -> FileRecord:
    return next(record for record in scan.records if record.path == path)


def _init_git_repo(root: Path) -> None:
    if shutil.which("git") is None:
        pytest.skip("git unavailable")
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)


def _write_files(root: Path, files: dict[str, str]) -> None:
    for path, content in files.items():
        write_atomic(root / path, content)
