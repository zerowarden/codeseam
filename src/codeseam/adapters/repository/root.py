from __future__ import annotations

from pathlib import Path

REPOSITORY_ROOT_MARKERS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "pyproject.toml",
        "package.json",
        "tsconfig.json",
        "Cargo.toml",
        "Package.swift",
        "go.mod",
        "pom.xml",
        "build.gradle",
        "settings.gradle",
    }
)


def detect_repo_root(explicit: Path | None = None, cwd: Path | None = None) -> Path:
    if explicit is not None:
        return explicit.resolve()
    current = (cwd or Path.cwd()).resolve()
    return _marker_root(current) or current


def _marker_root(cwd: Path) -> Path | None:
    for path in (cwd, *cwd.parents):
        if any((path / marker).exists() for marker in REPOSITORY_ROOT_MARKERS):
            return path.resolve()
    return None


__all__ = ["detect_repo_root"]
