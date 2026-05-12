from __future__ import annotations

from collections.abc import Mapping

from codeseam.adapters.languages import default_language_registry
from codeseam.adapters.languages.extraction import (
    FileAnalysisResult,
    analyze_language_file,
    language_context,
)
from codeseam.analysis import (
    FileWithoutFunctionUnits,
    FunctionInventory,
    FunctionRecord,
    RepositoryFacts,
    assign_ids,
)
from codeseam.cache import AnalysisCacheContext
from codeseam.config import Config


def build_function_inventory(
    config: Config,
    facts: RepositoryFacts,
    caches: AnalysisCacheContext | None = None,
    file_analysis: Mapping[str, FileAnalysisResult] | None = None,
) -> FunctionInventory:
    run_cache = caches.language if caches else None
    registry = default_language_registry()
    records: list[FunctionRecord] = []
    files_without_function_units: list[FileWithoutFunctionUnits] = []
    for relative_path in facts.selected_paths:
        file_record = facts.records_by_path[relative_path]
        result = file_analysis.get(relative_path) if file_analysis is not None else None
        if result is None:
            analysis_context = language_context(
                config.repo_root,
                relative_path,
                file_record,
                run_cache,
            )
            result = analyze_language_file(
                analysis_context,
                file_record,
                registry,
                caches,
            )
        records.extend(result.functions)
        if not result.functions:
            files_without_function_units.append(
                FileWithoutFunctionUnits(
                    file=relative_path,
                    language=file_record.language.lower(),
                    caveats=("no_function_units_found",),
                )
            )
    assigned = assign_ids(records)
    return FunctionInventory(
        records=tuple(assigned),
        selected_file_count=facts.selected_file_count,
        files_without_function_units=tuple(files_without_function_units),
    )


__all__ = [
    "build_function_inventory",
]
