from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

DOC_SUFFIXES = {".md", ".rst", ".txt"}
CONFIG_NAMES = {
    ".gitignore",
    ".pre-commit-config.yaml",
    "package.json",
    "pyproject.toml",
    "pytest.ini",
    "setup.cfg",
}
CONFIG_SUFFIXES = {".cfg", ".ini", ".json", ".toml", ".yaml", ".yml"}
TEST_MARKERS = {"test", "tests", "__tests__", "spec", "specs"}
FIXTURE_MARKERS = {"fixture", "fixtures", "golden", "snapshots"}
GENERATED_MARKERS = {"generated", "gen"}
VENDOR_MARKERS = {"vendor", "third_party", "third-party", "node_modules", ".yarn"}
BUILD_MARKERS = {"build", "dist", "coverage", ".next", ".nuxt"}


@dataclass(frozen=True)
class PathClassification:
    role: str
    is_generated: bool
    is_vendor: bool
    is_test: bool
    is_build_output: bool


def classify_path(
    path: Path,
    *,
    language_test_path: Callable[[Path], bool] | None = None,
) -> PathClassification:
    parts = {part.lower() for part in path.parts}
    name = path.name.lower()
    suffix = path.suffix.lower()

    is_fixture = bool(parts & FIXTURE_MARKERS)
    is_test = is_fixture or _looks_like_test(parts, path, name, language_test_path)
    is_generated = bool(parts & GENERATED_MARKERS) or "generated" in name
    is_vendor = bool(parts & VENDOR_MARKERS)
    is_build_output = bool(parts & BUILD_MARKERS)
    role = _role(
        name=name,
        suffix=suffix,
        is_fixture=is_fixture,
        is_test=is_test,
        is_generated=is_generated,
        is_vendor=is_vendor,
        is_build_output=is_build_output,
    )
    return PathClassification(
        role=role,
        is_generated=is_generated,
        is_vendor=is_vendor,
        is_test=is_test,
        is_build_output=is_build_output,
    )


def _looks_like_test(
    parts: set[str],
    path: Path,
    name: str,
    language_test_path: Callable[[Path], bool] | None,
) -> bool:
    suffix = "".join(Path(name).suffixes).lower()
    stem = name[: -len(suffix)] if suffix else name
    return (
        _general_test_name(stem, name)
        or bool(parts & TEST_MARKERS)
        or (language_test_path is not None and language_test_path(path))
    )


def _general_test_name(stem: str, name: str) -> bool:
    return (
        stem.startswith("test_")
        or stem.endswith("_test")
        or stem.endswith("_tests")
        or ".test." in name
        or ".spec." in name
        or name.startswith("test.")
        or name.startswith("spec.")
    )


def _role(  # noqa: PLR0913
    *,
    name: str,
    suffix: str,
    is_fixture: bool,
    is_test: bool,
    is_generated: bool,
    is_vendor: bool,
    is_build_output: bool,
) -> str:
    checks = [
        (is_vendor, "vendor"),
        (is_build_output, "build_output"),
        (is_generated, "generated"),
        (is_fixture, "fixture"),
        (is_test, "test"),
        (suffix in DOC_SUFFIXES, "documentation"),
        (name in CONFIG_NAMES or suffix in CONFIG_SUFFIXES, "configuration"),
    ]
    for matched, role in checks:
        if matched:
            return role
    return "source"
