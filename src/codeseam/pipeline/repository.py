from __future__ import annotations

from codeseam.adapters.languages import default_language_registry
from codeseam.adapters.repository.filesystem import select_files
from codeseam.adapters.repository.manifests import discover_repository_manifests
from codeseam.analysis import RepositoryScan
from codeseam.config import Config
from codeseam.output.artifacts.context import write_context_artifacts
from codeseam.platform import OutputPaths, as_json_object


def scan_repository(
    config: Config,
    paths: OutputPaths,
    *,
    write_artifacts: bool = False,
) -> RepositoryScan:
    selection = as_json_object(config.data.get("selection"))
    records, selected_paths = select_files(config.repo_root, selection)
    manifests = discover_repository_manifests(
        records,
        default_language_registry().manifest_matchers(),
    )
    if write_artifacts:
        write_context_artifacts(paths, records, selected_paths, manifests)
    return RepositoryScan(records=records, selected_paths=selected_paths, manifests=manifests)
