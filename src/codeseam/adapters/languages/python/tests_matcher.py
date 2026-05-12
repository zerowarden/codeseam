from __future__ import annotations

import configparser
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from codeseam.platform import GlobMatcher

DEFAULT_PYTHON_TEST_FILE_PATTERNS = (
    "*_test.py",
    "*_tests.py",
    "tests.py",
    "conftest.py",
)
DEFAULT_PYTHON_TEST_PATHS = ("test", "tests")


@dataclass(frozen=True, slots=True)
class PythonTestPathMatcher:
    file_patterns: tuple[str, ...] = DEFAULT_PYTHON_TEST_FILE_PATTERNS
    test_paths: tuple[str, ...] = DEFAULT_PYTHON_TEST_PATHS
    _file_matcher: GlobMatcher = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "_file_matcher",
            GlobMatcher.from_patterns(list(self.file_patterns)),
        )

    def matches_path(self, path: Path) -> bool:
        rel = path.as_posix().lower().strip("/")
        if path.suffix.lower() != ".py":
            return False
        return _under_test_path(rel, self.test_paths) or self._file_matcher.matches(rel)


def python_test_path_matcher(repo_root: Path | None = None) -> PythonTestPathMatcher:
    if repo_root is None:
        return PythonTestPathMatcher()
    config = _load_pytest_path_config(repo_root)
    return PythonTestPathMatcher(
        file_patterns=(*DEFAULT_PYTHON_TEST_FILE_PATTERNS, *config.file_patterns),
        test_paths=(*DEFAULT_PYTHON_TEST_PATHS, *config.test_paths),
    )


def matches_python_test_path(path: Path) -> bool:
    return PythonTestPathMatcher().matches_path(path)


@dataclass(frozen=True, slots=True)
class _PytestPathConfig:
    file_patterns: tuple[str, ...] = ()
    test_paths: tuple[str, ...] = ()


def _load_pytest_path_config(repo_root: Path) -> _PytestPathConfig:
    configs = [
        _pyproject_pytest_config(repo_root / "pyproject.toml"),
        _ini_pytest_config(repo_root / "pytest.ini", "pytest"),
        _ini_pytest_config(repo_root / "tox.ini", "pytest"),
        _ini_pytest_config(repo_root / "setup.cfg", "tool:pytest"),
    ]
    return _PytestPathConfig(
        file_patterns=tuple(
            dict.fromkeys(pattern for config in configs for pattern in config.file_patterns)
        ),
        test_paths=tuple(dict.fromkeys(path for config in configs for path in config.test_paths)),
    )


def _pyproject_pytest_config(path: Path) -> _PytestPathConfig:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return _PytestPathConfig()
    pytest_options = data.get("tool", {}).get("pytest", {}).get("ini_options", {})
    if not isinstance(pytest_options, dict):
        return _PytestPathConfig()
    return _PytestPathConfig(
        file_patterns=_config_values(pytest_options.get("python_files")),
        test_paths=_config_values(pytest_options.get("testpaths")),
    )


def _ini_pytest_config(path: Path, section: str) -> _PytestPathConfig:
    parser = configparser.ConfigParser()
    try:
        parser.read(path, encoding="utf-8")
    except configparser.Error:
        return _PytestPathConfig()
    if not parser.has_section(section):
        return _PytestPathConfig()
    return _PytestPathConfig(
        file_patterns=_config_values(parser.get(section, "python_files", fallback="")),
        test_paths=_config_values(parser.get(section, "testpaths", fallback="")),
    )


def _config_values(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(part.lower().strip("/") for part in value.split() if part)
    if isinstance(value, list):
        return tuple(part.lower().strip("/") for part in value if isinstance(part, str) and part)
    return ()


def _under_test_path(rel: str, test_paths: tuple[str, ...]) -> bool:
    return any(
        rel == test_path or rel.startswith(f"{test_path.rstrip('/')}/") for test_path in test_paths
    )


__all__ = [
    "PythonTestPathMatcher",
    "matches_python_test_path",
    "python_test_path_matcher",
]
