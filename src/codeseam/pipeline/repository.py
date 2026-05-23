from __future__ import annotations

from codeseam.adapters.languages import default_language_registry
from codeseam.adapters.repository.filesystem import select_files
from codeseam.adapters.repository.manifests import discover_repository_manifests
from codeseam.adapters.repository.scan_manifest import (
    load_scan_manifest,
    scan_manifest_path,
    store_scan_manifest,
)
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
    manifest_path = scan_manifest_path(config.cache_path())
    manifest = load_scan_manifest(manifest_path) if config.cache_enabled else None
    records, selected_paths = select_files(
        config.repo_root,
        selection,
        scan_manifest=manifest,
    )
    if manifest is not None:
        store_scan_manifest(manifest_path, manifest)
    manifests = discover_repository_manifests(
        records,
        default_language_registry().manifest_matchers(),
    )
    if write_artifacts:
        write_context_artifacts(paths, records, selected_paths, manifests)
    return RepositoryScan(records=records, selected_paths=selected_paths, manifests=manifests)
