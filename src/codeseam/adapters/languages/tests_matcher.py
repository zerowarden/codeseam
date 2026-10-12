from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from codeseam.adapters.languages.ecmascript.tests_matcher import matches_ecmascript_test_path
from codeseam.adapters.languages.python.tests_matcher import python_test_path_matcher

type TestPathMatcher = Callable[[Path], bool]


def test_matchers_for_repo(repo_root: Path) -> dict[str, TestPathMatcher]:
    """Per-language test-file conventions; shared test directories live in `classify_path`."""
    return {
        "Python": python_test_path_matcher(repo_root).matches_path,
        **dict.fromkeys(("JavaScript", "JSX", "TypeScript", "TSX"), matches_ecmascript_test_path),
    }


__all__ = ["TestPathMatcher", "test_matchers_for_repo"]
