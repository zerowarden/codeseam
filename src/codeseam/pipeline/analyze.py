from __future__ import annotations

import shutil
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from typing import TypeVar

from codeseam.analysis import (
    CompletenessSummary,
    FunctionInventory,
    RepositoryFacts,
    RepositoryScan,
    build_repository_facts,
)
from codeseam.cache import (
    AnalysisCacheContext,
    LanguageRunCache,
    PersistentCache,
    cached_repository_facts,
    persistent_cache,
    repository_facts_cache_key,
    store_repository_facts,
)
from codeseam.config import Config
from codeseam.output import (
    ReportArtifacts,
    ReportInputs,
    build_manifest,
    build_report_artifacts,
    function_inventory_records_payload,
    function_inventory_summary_payload,
    publish_reports,
    staging_paths,
    threshold_breached,
    write_debug_bundle_and_prune,
    write_report_artifacts,
    write_signature_artifacts,
)
from codeseam.pipeline.completeness import run_completeness
from codeseam.pipeline.file_analysis import RepositoryFileAnalysis, analyze_selected_files
from codeseam.pipeline.inventory import build_function_inventory
from codeseam.pipeline.progress import ProgressReporter
from codeseam.pipeline.repository import scan_repository
from codeseam.pipeline.repository_enrichment import (
    RepositoryEnrichment,
    build_repository_enrichment,
)
from codeseam.pipeline.semantics import (
    SemanticStageRuntime,
    run_semantic_enrichment_stage,
    semantic_enrichment_stats,
)
from codeseam.pipeline.signatures import (
    SignatureArtifacts,
    build_signature_artifacts,
)
from codeseam.platform import (
    Json,
    OutputPaths,
    file_locks,
    json_int,
    runtime_lock_paths,
    write_jsonable_atomic,
    write_jsonl_jsonable_atomic,
)
from codeseam.platform.storage import claim_storage_root
from codeseam.semantics import SemanticEnrichmentRun, typescript_provider

T = TypeVar("T")


@dataclass(frozen=True)
class AnalysisRun:
    selected_file_count: int
    skipped_file_count: int
    function_count: int
    repository_facts: RepositoryFacts
    report_artifacts: ReportArtifacts
    timings: Json
    signature_artifacts: SignatureArtifacts
    semantic_enrichment: SemanticEnrichmentRun
    completeness: CompletenessSummary
    file_diagnostics: dict[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class AnalysisPipelineRequest:
    config: Config
    paths: OutputPaths
    progress: ProgressReporter
    debug: bool = False


@dataclass(frozen=True)
class _StageResult[T]:
    value: T
    message: str


@dataclass(frozen=True)
class _InventoryStage:
    caches: AnalysisCacheContext
    inventory: FunctionInventory
    file_analysis: RepositoryFileAnalysis


@contextmanager
def _analysis_cache(config: Config) -> Iterator[PersistentCache]:
    output_root = config.output_root
    cache_path = config.cache_path
    with file_locks(runtime_lock_paths(output_root, cache_path)):
        claim_storage_root(config.repo_root, output_root)
        if config.cache_enabled:
            claim_storage_root(config.repo_root, cache_path)
        cache = persistent_cache(cache_path, enabled=config.cache_enabled)
        try:
            yield cache
        finally:
            cache.close()


def run_analysis_pipeline(request: AnalysisPipelineRequest) -> AnalysisRun:
    """Analyse into a staging root and publish only a finished run.

    A failure or Ctrl-C leaves the previous reports untouched.
    """

    with _analysis_cache(request.config) as cache:
        staging = staging_paths(request.paths)
        try:
            run = _AnalysisPipeline(replace(request, paths=staging), cache).run()
            publish_reports(staging, request.paths)
            return run
        finally:
            shutil.rmtree(staging.root, ignore_errors=True)


class _AnalysisPipeline:
    def __init__(self, request: AnalysisPipelineRequest, cache: PersistentCache) -> None:
        self.request = request
        self.config = request.config
        self.paths = request.paths
        self.progress = request.progress
        self.cache = cache
        self.started = time.perf_counter()

    def run(self) -> AnalysisRun:
        self._stage("Preparing analysis output", self._prepare_output)
        context = self._stage("Scanning repository", self._scan_repository)
        facts = self._stage(
            "Building repository facts",
            lambda: self._build_repository_facts(context),
        )
        repository_enrichment = build_repository_enrichment(facts)
        inventory_stage = self._stage(
            "Extracting function inventory",
            lambda: self._analyze_files(facts),
        )
        signature_artifacts = self._stage(
            "Analysing structural signatures",
            lambda: self._analyse_signatures(facts, inventory_stage),
        )
        semantic_enrichment = self._stage(
            "Planning semantic enrichment",
            lambda: self._semantic_enrichment(signature_artifacts, repository_enrichment),
        )
        completeness = run_completeness(
            facts,
            diagnostics=inventory_stage.file_analysis.diagnostics,
            function_count=len(inventory_stage.inventory.records),
            comparison_stats=_relation_comparison_stats(signature_artifacts),
            capabilities=repository_enrichment.adapter_capabilities,
            semantic_enrichment=semantic_enrichment,
            clusters=signature_artifacts.clusters,
        )
        report_artifacts = self._stage(
            "Building report artifacts",
            lambda: self._build_reports(
                facts,
                signature_artifacts,
                repository_enrichment,
                semantic_enrichment,
                completeness,
            ),
        )
        self._stage("Finalising artifacts", self._finalise_artifacts)
        elapsed = time.perf_counter() - self.started
        return AnalysisRun(
            selected_file_count=facts.selected_file_count,
            skipped_file_count=facts.skipped_file_count,
            function_count=len(inventory_stage.inventory.records),
            repository_facts=facts,
            report_artifacts=report_artifacts,
            timings={
                "elapsed_seconds": round(elapsed, 3),
                "cache": self.cache.run_stats(),
                "relations": _relation_comparison_stats(signature_artifacts),
                "semantics": semantic_enrichment_stats(semantic_enrichment),
            },
            signature_artifacts=signature_artifacts,
            semantic_enrichment=semantic_enrichment,
            completeness=completeness,
            file_diagnostics=inventory_stage.file_analysis.diagnostics,
        )

    def _stage(self, name: str, fn: Callable[[], _StageResult[T]]) -> T:
        with self.progress.stage(name) as stage:
            result = fn()
            stage.finish(result.message)
            return result.value

    def _prepare_output(self) -> _StageResult[None]:
        self.paths.ensure_audit(include_internal=self.request.debug)
        return _StageResult(
            None,
            "Prepared analysis output: 1 output root, schemas ready",
        )

    def _scan_repository(self) -> _StageResult[RepositoryScan]:
        context = scan_repository(
            self.config,
            self.paths,
            write_artifacts=self.request.debug,
        )
        skipped = max(0, len(context.records) - len(context.selected_paths))
        return _StageResult(
            context,
            f"Discovered files: {len(context.selected_paths)} analysed, {skipped} skipped",
        )

    def _build_repository_facts(self, context: RepositoryScan) -> _StageResult[RepositoryFacts]:
        facts, cache_status = self._cached_repository_facts(context)
        return _StageResult(
            facts,
            "Built repository facts: "
            f"{facts.selected_file_count} analysis files, "
            f"{len(facts.manifests)} manifests"
            f"{cache_status}",
        )

    def _cached_repository_facts(self, context: RepositoryScan) -> tuple[RepositoryFacts, str]:
        if not self.config.cache_enabled:
            return build_repository_facts(context), ""
        key = repository_facts_cache_key(context, self.config.selection)
        cached = cached_repository_facts(self.cache, key)
        if cached is not None:
            return cached, ", cache hit"
        facts = build_repository_facts(context)
        store_repository_facts(self.cache, key, facts)
        return facts, ", cache miss"

    def _analyze_files(self, facts: RepositoryFacts) -> _StageResult[_InventoryStage]:
        caches = AnalysisCacheContext(
            persistent=self.cache,
            file_analysis_enabled=self.config.cache_enabled,
            relation_pair_enabled=self.config.cache_enabled,
            language=LanguageRunCache(),
        )
        file_analysis = analyze_selected_files(
            self.config,
            facts,
            caches,
        )
        inventory = build_function_inventory(
            self.config,
            facts,
            caches,
            file_analysis.by_path,
        )
        if self.request.debug:
            write_jsonl_jsonable_atomic(
                self.paths.artifact("functions"),
                function_inventory_records_payload(inventory),
            )
            write_jsonable_atomic(
                self.paths.artifact("function_inventory_summary"),
                function_inventory_summary_payload(inventory),
                pretty=True,
            )
        files_without_functions = len(inventory.files_without_function_units)
        failed_files = len(file_analysis.diagnostics)
        return _StageResult(
            _InventoryStage(
                caches=caches,
                inventory=inventory,
                file_analysis=file_analysis,
            ),
            "Extracted function inventory: "
            f"{len(inventory.records)} functions found, "
            f"{files_without_functions} files without functions, "
            f"{failed_files} files failed extraction",
        )

    def _analyse_signatures(
        self,
        facts: RepositoryFacts,
        inventory_stage: _InventoryStage,
    ) -> _StageResult[SignatureArtifacts]:
        signature_artifacts = build_signature_artifacts(
            self.config,
            facts,
            inventory_stage.inventory.records,
            inventory_stage.caches,
            inventory_stage.file_analysis.by_path,
            inventory_stage.file_analysis.policy_constants,
        )
        if self.request.debug:
            write_signature_artifacts(
                self.paths, signature_artifacts.records, signature_artifacts.clusters
            )
        return _StageResult(
            signature_artifacts,
            f"Analysed structural signatures: {len(signature_artifacts.records)} signatures",
        )

    def _build_reports(
        self,
        facts: RepositoryFacts,
        signature_artifacts: SignatureArtifacts,
        repository_enrichment: RepositoryEnrichment,
        semantic_enrichment: SemanticEnrichmentRun,
        completeness: CompletenessSummary,
    ) -> _StageResult[ReportArtifacts]:
        manifest = build_manifest(self.config, selected_file_count=facts.selected_file_count)
        write_jsonable_atomic(self.paths.artifact("manifest"), manifest, pretty=True)
        report_artifacts = build_report_artifacts(
            ReportInputs(
                config=self.config,
                paths=self.paths,
                facts=facts,
                clusters=signature_artifacts.clusters,
                signatures=signature_artifacts.records,
                manifest=manifest,
                adapter_capabilities=repository_enrichment.adapter_capabilities,
                semantic_enrichment=semantic_enrichment,
                completeness=completeness,
                debug=self.request.debug,
            )
        )
        write_report_artifacts(
            self.paths,
            report_artifacts,
            write_internal=self.request.debug,
        )
        return _StageResult(
            report_artifacts,
            "Built report artifacts: "
            f"{len(report_artifacts.analysis_targets)} analysis targets, "
            f"{len(report_artifacts.observations)} observations",
        )

    def _semantic_enrichment(
        self,
        signature_artifacts: SignatureArtifacts,
        repository_enrichment: RepositoryEnrichment,
    ) -> _StageResult[SemanticEnrichmentRun]:
        choice = typescript_provider(self.config.repo_root, trusted=self.config.trust_project_code)
        run = run_semantic_enrichment_stage(
            repo_root=str(self.config.repo_root),
            mode=self.config.semantic_mode,
            signature_artifacts=signature_artifacts,
            repository_enrichment=repository_enrichment,
            runtime=SemanticStageRuntime(
                provider=choice.provider,
                cache=self.cache if self.config.cache_enabled else None,
                unavailable_reason=choice.unavailable_reason,
            ),
        )
        return _StageResult(
            run,
            "Planned semantic enrichment: "
            f"{len(run.requests)} request batches, "
            f"{sum(len(request.items) for request in run.requests)} candidate items, "
            f"status {run.status}",
        )

    def _finalise_artifacts(self) -> _StageResult[None]:
        write_debug_bundle_and_prune(
            self.paths,
            write_bundle=self.request.debug,
        )
        mode = "debug evidence bundle written" if self.request.debug else "internal writes skipped"
        return _StageResult(None, f"Finalised artifacts: {mode}")


def _relation_comparison_stats(signature_artifacts: SignatureArtifacts) -> Json:
    stats: Json = {}
    for cluster in signature_artifacts.clusters.clusters:
        if not cluster.enrichment:
            continue
        for key, value in cluster.enrichment.candidate_generation.comparison_stats.items():
            if key.startswith("profile_"):
                continue
            stats[key] = json_int(stats.get(key)) + int(value)
    return stats


def analysis_exit_code(
    report_artifacts: ReportArtifacts,
    *,
    threshold_exit: int,
    ok_exit: int,
) -> int:
    return threshold_exit if threshold_breached(report_artifacts) else ok_exit
