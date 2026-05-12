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
ANALYSIS_LANGUAGES = {"Python", "TypeScript", "TSX", "JavaScript", "JSX"}


def detect_language(path: Path) -> str:
    return LANGUAGE_BY_SUFFIX.get(path.suffix.lower(), "unknown")


def is_analysis_language(language: str) -> bool:
    return language in ANALYSIS_LANGUAGES
