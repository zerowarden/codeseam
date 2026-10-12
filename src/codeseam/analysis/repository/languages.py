from __future__ import annotations

from pathlib import Path

LANGUAGE_BY_SUFFIX = {
    ".py": "Python",
    ".ts": "TypeScript",
    ".tsx": "TSX",
    ".mts": "TypeScript",
    ".cts": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JSX",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".md": "Markdown",
    ".json": "JSON",
    ".toml": "TOML",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".cfg": "INI",
    ".ini": "INI",
}
# Source languages without an adapter: named so a completeness summary can count them.
OTHER_SOURCE_LANGUAGE_BY_SUFFIX = {
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".kt": "Kotlin",
    ".swift": "Swift",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cs": "C#",
    ".c": "C",
    ".h": "C",
    ".cc": "C++",
    ".cpp": "C++",
    ".hpp": "C++",
    ".scala": "Scala",
}
ANALYSIS_LANGUAGES = {"Python", "TypeScript", "TSX", "JavaScript", "JSX"}
OTHER_SOURCE_LANGUAGES = frozenset(OTHER_SOURCE_LANGUAGE_BY_SUFFIX.values())


def detect_language(path: Path) -> str:
    suffix = path.suffix.lower()
    return LANGUAGE_BY_SUFFIX.get(suffix) or OTHER_SOURCE_LANGUAGE_BY_SUFFIX.get(suffix, "unknown")


def is_analysis_language(language: str) -> bool:
    return language in ANALYSIS_LANGUAGES
