from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from codeseam.adapters.languages.ecmascript.tests_matcher import matches_ecmascript_test_name
from codeseam.adapters.languages.python.tests_matcher import python_test_path_matcher
from codeseam.analysis import has_common_test_path_part


@dataclass(frozen=True)
class LanguageTestMatcher:
    matches_path: Callable[[Path], bool]


def _ecmascript_matcher(path: Path) -> bool:
    name = path.name.lower()
    suffix = path.suffix.lower()
    stem = name[: -len(suffix)] if suffix else name
    return matches_ecmascript_test_name(stem, suffix)


TEST_MATCHER_BY_LANGUAGE: dict[str, LanguageTestMatcher] = {
    "Python": LanguageTestMatcher(matches_path=python_test_path_matcher().matches_path),
    "JavaScript": LanguageTestMatcher(matches_path=_ecmascript_matcher),
    "JSX": LanguageTestMatcher(matches_path=_ecmascript_matcher),
    "TypeScript": LanguageTestMatcher(matches_path=_ecmascript_matcher),
    "TSX": LanguageTestMatcher(matches_path=_ecmascript_matcher),
}


def test_matchers_for_repo(repo_root: Path) -> dict[str, LanguageTestMatcher]:
    python_matcher = python_test_path_matcher(repo_root)
    return {
        **TEST_MATCHER_BY_LANGUAGE,
        "Python": LanguageTestMatcher(matches_path=python_matcher.matches_path),
    }


def test_matcher_for_language(
    language: str,
    *,
    repo_root: Path | None = None,
) -> LanguageTestMatcher | None:
    if language == "Python":
        return LanguageTestMatcher(matches_path=python_test_path_matcher(repo_root).matches_path)
    return TEST_MATCHER_BY_LANGUAGE.get(language)


def is_test_path_for_language(language: str, path: str) -> bool:
    test_path = Path(path)
    if _matches_common_test_path(test_path):
        return True
    matcher = test_matcher_for_language(language)
    if matcher is None:
        return False
    return matcher.matches_path(test_path)


def _matches_common_test_path(path: Path) -> bool:
    return has_common_test_path_part(path.parts)


__all__ = [
    "LanguageTestMatcher",
    "TEST_MATCHER_BY_LANGUAGE",
    "is_test_path_for_language",
    "test_matcher_for_language",
    "test_matchers_for_repo",
]
