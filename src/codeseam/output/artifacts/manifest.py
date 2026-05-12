from __future__ import annotations

import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path

from codeseam.config import Config
from codeseam.platform import Json, OutputPaths


def build_manifest(  # noqa: PLR0913
    config: Config,
    *,
    scope: str = "full",
    base_ref: str | None = None,
    selected_file_count: int = 0,
) -> Json:
    created_at = datetime.now(UTC)
    paths = OutputPaths(config.path("output", "root"))
    return {
        "schema_version": "codeseam.manifest.v1",
        "run_id": f"{created_at.strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}",
        "created_at": created_at.isoformat(),
        "repo_root": ".",
        "scope": scope,
        "base_ref": base_ref,
        "head_ref": _head_ref(config.repo_root),
        "config_hash": config.config_hash,
        "selected_file_count": selected_file_count,
        "artifacts": paths.artifact_refs(),
    }


def _head_ref(repo_root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None
