from __future__ import annotations

from pathlib import Path

import pytest
from helpers import assert_contains

from .fixtures import CliRunner


@pytest.mark.integration
def test_profile_prints_profile_stats(app_repo: Path, cli_runner: CliRunner) -> None:
    del app_repo

    output = cli_runner(["profile", "--limit", "3"]).stdout
    assert_contains(
        output,
        [
            "analysis_seconds=",
            "profile_summary:",
            "selected_file_count=",
            "operation_features_count=",
            "top_clusters_by_enrichment_ms:",
            "Ordered by:",
        ],
    )
