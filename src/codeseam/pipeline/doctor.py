"""`codeseam doctor`: check that an analysis can run, without running it.

Every check is read-only. It never starts the semantic worker and never
imports or runs code from the analysed repository.
"""

from __future__ import annotations

import os
import platform
import shutil
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from codeseam.adapters.languages import (
    LanguageAdapter,
    LanguageAnalysisContext,
    default_language_registry,
)
from codeseam.adapters.repository.filesystem import select_files
from codeseam.analysis import is_analysis_language
from codeseam.cache import cache_stats
from codeseam.config import Config, load_config
from codeseam.platform import ConfigError, Json, display_path, loads_json
from codeseam.platform.storage import is_owned_storage_root
from codeseam.semantics import SemanticMode, typescript_worker_script
from codeseam.version import ANALYSIS_FINGERPRINT, package_version

MIN_PYTHON = (3, 12)
PARSER_DISTRIBUTIONS = ("tree-sitter", "tree-sitter-javascript", "tree-sitter-typescript")
# One small function per language: each adapter must find exactly one.
PARSER_PROBES = {
    "Python": ("probe.py", "def probe(value):\n    return value\n"),
    "TypeScript": ("probe.ts", "function probe(value: number): number { return value; }\n"),
    "TSX": ("probe.tsx", "function probe(value: number) { return <b>{value}</b>; }\n"),
    "JavaScript": ("probe.js", "function probe(value) { return value; }\n"),
    "JSX": ("probe.jsx", "function probe(value) { return <b>{value}</b>; }\n"),
}
TYPESCRIPT_PACKAGE = Path("node_modules", "typescript", "package.json")


class CheckStatus(StrEnum):
    OK = "ok"
    INFO = "info"
    WARN = "warn"
    FAIL = "fail"


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    area: str
    name: str
    status: CheckStatus
    detail: str


@dataclass(frozen=True, slots=True)
class DoctorReport:
    repo_root: Path
    checks: tuple[DoctorCheck, ...]
    settings: Json

    @property
    def failed(self) -> bool:
        return any(check.status is CheckStatus.FAIL for check in self.checks)

    def counts(self) -> dict[str, int]:
        found = Counter(check.status for check in self.checks)
        return {status.value: found[status] for status in CheckStatus}

    def payload(self) -> Json:
        return {
            "schema_version": "codeseam.doctor.v1",
            "repo_root": str(self.repo_root),
            "summary": self.counts(),
            "checks": [
                {
                    "area": check.area,
                    "name": check.name,
                    "status": check.status.value,
                    "detail": check.detail,
                }
                for check in self.checks
            ],
            "settings": self.settings,
        }


def run_doctor(repo_root: Path) -> DoctorReport:
    """Check the runtime, configuration, storage, parsers, selection, cache and provider."""

    checks = [*_runtime_checks(repo_root)]
    try:
        config = load_config(repo_root)
    except ConfigError as exc:
        checks.append(_check("config", "configuration", CheckStatus.FAIL, str(exc)))
        return DoctorReport(repo_root, tuple(checks), {})
    sources = ", ".join(config.sources)
    checks.append(_check("config", "configuration", CheckStatus.OK, f"sources: {sources}"))
    for area_checks in (
        _storage_checks,
        _parser_checks,
        _selection_checks,
        _cache_checks,
        _semantic_checks,
    ):
        checks.extend(area_checks(config))
    return DoctorReport(config.repo_root, tuple(checks), effective_settings(config))


def effective_settings(config: Config) -> Json:
    root = config.repo_root
    return {
        "repo_root": str(root),
        "output.root": display_path(root, config.output_root),
        "cache.path": display_path(root, config.cache_path),
        "cache.enabled": config.cache_enabled,
        "selection.include": list(config.selection.include),
        "selection.exclude": list(config.selection.exclude),
        "relations.split_test": config.split_test,
        "agent_summary.max_targets": config.agent_summary_max_targets,
        "semantics.mode": config.semantic_mode.value,
        "semantics.trust_project_code": config.trust_project_code,
        "config_hash": config.config_hash,
    }


def _check(area: str, name: str, status: CheckStatus, detail: str) -> DoctorCheck:
    return DoctorCheck(area, name, status, detail)


def _runtime_checks(repo_root: Path) -> list[DoctorCheck]:
    python_ok = sys.version_info >= MIN_PYTHON
    git = shutil.which("git")
    return [
        _check(
            "runtime",
            "codeseam",
            CheckStatus.INFO,
            f"version {package_version()}, analysis fingerprint {ANALYSIS_FINGERPRINT}",
        ),
        _check(
            "runtime",
            "python",
            CheckStatus.OK if python_ok else CheckStatus.FAIL,
            f"{platform.python_implementation()} {platform.python_version()}"
            + ("" if python_ok else f"; Codeseam needs {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or later"),
        ),
        _check(
            "runtime",
            "git",
            CheckStatus.OK if git else CheckStatus.WARN,
            f"{git}; .gitignore rules apply"
            if git
            else "not found; files that .gitignore excludes will be analysed",
        ),
        _check(
            "runtime",
            "repository root",
            CheckStatus.INFO,
            f"{repo_root}" + (" (Git repository)" if (repo_root / ".git").exists() else ""),
        ),
    ]


def _storage_checks(config: Config) -> list[DoctorCheck]:
    checks = [_storage_check("output root", config.repo_root, config.output_root)]
    if config.cache_enabled:
        checks.append(_storage_check("cache path", config.repo_root, config.cache_path))
    else:
        checks.append(_check("storage", "cache path", CheckStatus.INFO, "cache is disabled"))
    return checks


def _storage_check(name: str, root: Path, path: Path) -> DoctorCheck:
    shown = display_path(root, path)
    if path.exists():
        if is_owned_storage_root(root, path):
            return _check("storage", name, CheckStatus.OK, f"{shown} (owned by Codeseam)")
        return _check(
            "storage", name, CheckStatus.FAIL, f"{shown} exists and is not owned by Codeseam"
        )
    parent = next(item for item in (path, *path.parents) if item.exists())
    if os.access(parent, os.W_OK):
        return _check("storage", name, CheckStatus.OK, f"{shown} (will be created)")
    return _check("storage", name, CheckStatus.FAIL, f"{shown} cannot be created in {parent}")


def _parser_checks(config: Config) -> list[DoctorCheck]:
    del config
    versions = ", ".join(f"{name} {_distribution_version(name)}" for name in PARSER_DISTRIBUTIONS)
    checks = [_check("parsers", "parser packages", CheckStatus.INFO, versions)]
    registry = default_language_registry()
    with tempfile.TemporaryDirectory(prefix="codeseam-doctor-") as directory:
        for language, (name, source) in PARSER_PROBES.items():
            adapter = registry.adapter_for_language(language)
            if adapter is None:
                checks.append(_check("parsers", language, CheckStatus.FAIL, "no adapter"))
                continue
            path = Path(directory, name)
            path.write_text(source, encoding="utf-8")
            checks.append(_probe(adapter, LanguageAnalysisContext(path, name, "source", language)))
    return checks


def _probe(adapter: LanguageAdapter, context: LanguageAnalysisContext) -> DoctorCheck:
    """Parse one known function; a parser that cannot is broken or missing a grammar."""

    name = adapter.adapter_id.value
    try:
        found = len(adapter.extract_analysis(context).signatures)
    except Exception as exc:  # noqa: BLE001 - any parser failure is the finding
        return _check("parsers", context.language, CheckStatus.FAIL, f"{name}: {exc}")
    if found != 1:
        detail = f"{name}: found {found} functions, not 1"
        return _check("parsers", context.language, CheckStatus.FAIL, detail)
    return _check("parsers", context.language, CheckStatus.OK, name)


def _selection_checks(config: Config) -> list[DoctorCheck]:
    records, selected = select_files(config.repo_root, config.selection)
    languages = Counter(
        record.language for record in records if is_analysis_language(record.language)
    )
    roles = Counter(record.role for record in records if is_analysis_language(record.language))
    if not selected:
        return [
            _check(
                "selection",
                "files to analyse",
                CheckStatus.WARN,
                "no source files match the selection; check selection.include and the excludes",
            )
        ]
    by_language = ", ".join(f"{language} {count}" for language, count in sorted(languages.items()))
    by_role = ", ".join(f"{role} {count}" for role, count in sorted(roles.items()))
    return [
        _check("selection", "files to analyse", CheckStatus.OK, f"{len(selected)}: {by_language}"),
        _check("selection", "file roles", CheckStatus.INFO, by_role),
    ]


def _cache_checks(config: Config) -> list[DoctorCheck]:
    if not config.cache_enabled:
        return []
    stats = cache_stats(config.cache_path)
    if not stats.get("exists"):
        return [
            _check("cache", "persistent cache", CheckStatus.INFO, "empty; the first run is cold")
        ]
    return [
        _check(
            "cache",
            "persistent cache",
            CheckStatus.INFO,
            f"{stats.get('entry_count', 0)} entries",
        )
    ]


def _semantic_checks(config: Config) -> list[DoctorCheck]:
    mode = config.semantic_mode
    if mode is SemanticMode.OFF:
        return [_check("semantics", "semantic provider", CheckStatus.INFO, "semantics.mode is off")]
    missing = CheckStatus.FAIL if mode is SemanticMode.REQUIRED else CheckStatus.WARN
    checks = [
        _check("semantics", "mode", CheckStatus.INFO, mode.value),
        _check(
            "semantics",
            "trust",
            CheckStatus.OK if config.trust_project_code else missing,
            "trust_project_code is true; the worker may load the repository's TypeScript"
            if config.trust_project_code
            else "trust_project_code is false; the worker will not start",
        ),
    ]
    node = shutil.which("node")
    checks.append(
        _check("semantics", "node", CheckStatus.OK if node else missing, node or "not on PATH")
    )
    worker = typescript_worker_script()
    checks.append(
        _check(
            "semantics",
            "worker",
            CheckStatus.OK if worker.is_file() else CheckStatus.FAIL,
            str(worker) if worker.is_file() else f"missing: {worker}",
        )
    )
    typescript = _typescript_version(config.repo_root)
    checks.append(
        _check(
            "semantics",
            "typescript package",
            CheckStatus.OK if typescript else CheckStatus.WARN,
            f"{typescript} (read from package.json, not loaded)"
            if typescript
            else "not found in node_modules; only ownership facts are available",
        )
    )
    return checks


def _typescript_version(repo_root: Path) -> str:
    try:
        data = loads_json((repo_root / TYPESCRIPT_PACKAGE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(data.get("version", "")) if isinstance(data, dict) else ""


def _distribution_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "missing"


__all__ = ["CheckStatus", "DoctorCheck", "DoctorReport", "effective_settings", "run_doctor"]
