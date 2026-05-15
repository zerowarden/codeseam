from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from codeseam.adapters.languages import LanguageAnalysisContext, LanguageRegistry
from codeseam.analysis import FileRecord, FunctionRecord, PolicyConstant, SignatureAnalysis
from codeseam.cache import (
    AnalysisCacheContext,
    FileAnalysisCacheRequest,
    FileAnalysisCacheResult,
    LanguageRunCache,
    PrefetchedSignatures,
    cached_file_analysis,
    signature_analyses_from_records,
    store_file_analysis,
)


@dataclass(frozen=True, slots=True)
class FileAnalysisResult:
    """Compact file-analysis result retained by the pipeline."""

    functions: tuple[FunctionRecord, ...]
    signatures: tuple[SignatureAnalysis, ...]
    policy_constants: tuple[PolicyConstant, ...] = ()


def language_context(
    repo_root: Path,
    relative_path: str,
    file_record: FileRecord,
    run_cache: LanguageRunCache | None = None,
) -> LanguageAnalysisContext:
    return LanguageAnalysisContext(
        path=repo_root / relative_path,
        relative_path=relative_path,
        role=file_record.role,
        language=file_record.language,
        content_hash=file_record.content_hash,
        run_cache=run_cache,
    )


def analyze_language_file(
    context: LanguageAnalysisContext,
    file_record: FileRecord,
    registry: LanguageRegistry,
    caches: AnalysisCacheContext | None,
    *,
    prefetched_signatures: PrefetchedSignatures | None = None,
) -> FileAnalysisResult:
    adapter = registry.adapter_for_language(context.language)
    if adapter is None:
        return FileAnalysisResult(functions=(), signatures=(), policy_constants=())
    if caches is not None and caches.language is not None:
        context = replace(context, run_cache=caches.language)
    if caches is None:
        analysis = adapter.extract_analysis(context)
        functions = analysis.functions
        signatures = signature_analyses_from_records(analysis.signatures)
        policy_constants = analysis.policy_constants
        del analysis
        return FileAnalysisResult(
            functions=functions,
            signatures=signatures,
            policy_constants=policy_constants,
        )

    cached = cached_file_analysis(
        FileAnalysisCacheRequest(
            context=context,
            file_record=file_record,
            adapter_id=adapter.adapter_id.value,
            supports_policy_constants=adapter.capabilities.policy_constants,
        ),
        caches=caches,
        prefetched_signatures=prefetched_signatures,
    )
    if cached.complete:
        return FileAnalysisResult(
            functions=cached.functions or (),
            signatures=cached.signatures or (),
            policy_constants=cached.policy_constants or (),
        )

    analysis = adapter.extract_analysis(context)
    extracted_functions = analysis.functions
    extracted_signatures = analysis.signatures if cached.signatures is None else ()
    extracted_policy_constants = analysis.policy_constants
    del analysis
    functions = cached.functions if cached.functions is not None else extracted_functions
    signatures = (
        cached.signatures
        if cached.signatures is not None
        else signature_analyses_from_records(extracted_signatures)
    )
    policy_constants = (
        cached.policy_constants
        if cached.policy_constants is not None
        else extracted_policy_constants
    )
    if caches.file_analysis_enabled:
        store_file_analysis(
            context,
            file_record,
            adapter.adapter_id.value,
            caches=caches,
            values=FileAnalysisCacheResult(
                functions=tuple(functions) if cached.functions is None else None,
                signatures=tuple(signatures) if cached.signatures is None else None,
                policy_constants=(
                    tuple(policy_constants)
                    if cached.policy_constants is None and adapter.capabilities.policy_constants
                    else None
                ),
            ),
        )
    return FileAnalysisResult(
        functions=tuple(functions),
        signatures=tuple(signatures),
        policy_constants=tuple(policy_constants),
    )


__all__ = ["FileAnalysisResult", "analyze_language_file", "language_context"]
