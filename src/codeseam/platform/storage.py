"""Ownership rules for directories Codeseam may overwrite or delete.

Output and cache roots come from configuration, which a repository can supply.
Cleanup must therefore never touch a directory Codeseam does not own: the
repository root or its parents, or an existing directory that was not created
by Codeseam.
"""

from __future__ import annotations

from pathlib import Path

from codeseam.platform.errors import ConfigError
from codeseam.platform.paths import PROJECT_DIR

OWNERSHIP_MARKER = ".codeseam-owned"
OWNERSHIP_MARKER_TEXT = "Created by Codeseam. Codeseam may overwrite or delete this directory.\n"


def validate_storage_root(repo_root: Path, path: Path, *, label: str) -> None:
    resolved = path.resolve(strict=False)
    repo = repo_root.resolve(strict=False)
    if resolved == repo or resolved in repo.parents:
        raise ConfigError(f"{label} must not be the repository root or one of its parents: {path}")
    if resolved.exists() and not is_owned_storage_root(repo, resolved):
        raise ConfigError(
            f"{label} already exists and is not managed by Codeseam: {path}. "
            f"Use a new or empty directory, or add a {OWNERSHIP_MARKER} file to it."
        )


def is_owned_storage_root(repo_root: Path, path: Path) -> bool:
    if not path.is_dir():
        return False
    return (
        _is_project_storage(repo_root, path)
        or (path / OWNERSHIP_MARKER).is_file()
        or not any(path.iterdir())
    )


def claim_storage_root(repo_root: Path, path: Path) -> None:
    """Create a storage root and mark it as Codeseam-owned when it is external."""

    path.mkdir(parents=True, exist_ok=True)
    marker = path / OWNERSHIP_MARKER
    if not _is_project_storage(repo_root, path) and not marker.exists():
        marker.write_text(OWNERSHIP_MARKER_TEXT, encoding="utf-8")


def _is_project_storage(repo_root: Path, path: Path) -> bool:
    return path.resolve(strict=False).is_relative_to(
        (repo_root / PROJECT_DIR).resolve(strict=False)
    )


__all__ = [
    "OWNERSHIP_MARKER",
    "claim_storage_root",
    "is_owned_storage_root",
    "validate_storage_root",
]
