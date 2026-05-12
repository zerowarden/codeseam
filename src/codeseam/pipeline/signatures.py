from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from codeseam.adapters.languages import (
    LanguageAdapter,
    LanguageRegistry,
    RelationDetailProvider,
    RelationDetailRequest,
    default_language_registry,
    relation_detail_provider,
)
from codeseam.adapters.languages.extraction import (
    FileAnalysisResult,
    analyze_language_file,
    language_context,
)
from codeseam.analysis import (
    Clusters,
    FileRecord,
    FunctionRecord,
    PolicyConstant,
    RepositoryFacts,
    SignatureAnalysis,
    SignatureAnalysisFeatures,
    build_clusters,
    build_policy_constant_clusters,
    signature_analysis_key,
)
from codeseam.cache import (
    AnalysisCacheContext,
    LanguageRunCache,
    cached_relation_detail_feature_map,
    cached_relation_pair_builder,
    relation_detail_cache_key,
    relation_detail_identity,
    store_relation_detail_feature_map,
)
from codeseam.config import Config
from codeseam.pipeline.file_analysis import analyze_selected_files


@dataclass(frozen=True)
class SignatureArtifacts:
    records: list[SignatureAnalysis]
    clusters: Clusters


@dataclass(frozen=True)
class _RelationHydrationContext:
    repo_root: Path
    facts: RepositoryFacts
    registry: LanguageRegistry
    function_by_anchor: dict[tuple[str, int, str], FunctionRecord]
    caches: AnalysisCacheContext | None
    run_cache: LanguageRunCache | None


@dataclass(frozen=True)
class _RelationDetailHydrationPlan:
    signature: SignatureAnalysis
    file_record: FileRecord
    function: FunctionRecord | None
    provider: RelationDetailProvider
    cache_key: str


def build_signature_artifacts(  # noqa: PLR0913
    config: Config,
    facts: RepositoryFacts,
    functions: Sequence[FunctionRecord],
    caches: AnalysisCacheContext | None = None,
    file_analysis: Mapping[str, FileAnalysisResult] | None = None,
    policy_constants: tuple[PolicyConstant, ...] = (),
) -> SignatureArtifacts:
    run_cache = caches.language if caches else None
    registry = default_language_registry()
    function_by_anchor = {
        (function.file, function.start_line, function.symbol): function for function in functions
    }
    signatures: list[SignatureAnalysis] = []
    policy_items = list(policy_constants)
    if file_analysis is None:
        analysis = analyze_selected_files(config, facts, caches)
        file_analysis = analysis.by_path
        policy_items.extend(analysis.policy_constants)
    for relative_path in facts.selected_paths:
        file_record = facts.records_by_path[relative_path]
        result = file_analysis.get(relative_path)
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
        function_by_anchor.update(
            {
                (function.file, function.start_line, function.symbol): function
                for function in result.functions
            }
        )
        signatures.extend(result.signatures)
    signatures = _assign_ids(_attach_functions(signatures, function_by_anchor))
    clusters = Clusters(
        clusters=build_clusters(
            signatures,
            relation_pair_builder=cached_relation_pair_builder(caches),
            split_test=config.relation_policy_enabled("split_test"),
            feature_hydrator=_relation_feature_hydrator(
                _RelationHydrationContext(
                    repo_root=config.repo_root,
                    facts=facts,
                    registry=registry,
                    function_by_anchor=function_by_anchor,
                    caches=caches,
                    run_cache=run_cache,
                )
            ),
        ),
        policy_constant_clusters=tuple(build_policy_constant_clusters(policy_items)),
    )
    return SignatureArtifacts(
        records=signatures,
        clusters=clusters,
    )


def _attach_functions(
    signatures: list[SignatureAnalysis],
    function_by_anchor: dict[tuple[str, int, str], FunctionRecord],
) -> list[SignatureAnalysis]:
    updated: list[SignatureAnalysis] = []
    for signature in signatures:
        core = signature.core
        key = (core.file, core.start_line, core.symbol)
        if function := function_by_anchor.get(key):
            core = replace(core, function_id=function.function_id)
            updated.append(replace(signature, core=core))
        else:
            updated.append(signature)
    return updated


def _assign_ids(signatures: list[SignatureAnalysis]) -> list[SignatureAnalysis]:
    ordered = sorted(
        signatures,
        key=lambda item: (
            item.core.file,
            item.core.start_line,
            item.core.symbol,
            item.core.canonical_shape,
        ),
    )
    updated: list[SignatureAnalysis] = []
    for index, signature in enumerate(ordered, 1):
        signature_id = f"sigrec_{index:06d}"
        updated.append(
            replace(
                signature,
                core=replace(signature.core, signature_id=signature_id),
                features=replace(signature.features, signature_id=signature_id),
                output=replace(signature.output, signature_id=signature_id),
            )
        )
    return updated


def _relation_feature_hydrator(
    context: _RelationHydrationContext,
) -> Callable[[Sequence[SignatureAnalysis]], list[SignatureAnalysis]]:
    """Return a relation-detail loader scoped to this analysis run.

    Signature extraction keeps the hot ``SignatureCore`` path compact. Cluster
    enrichment calls this hydrator only for members that actually enter relation
    scoring. The generic pipeline passes selected typed anchors back to the
    language adapter; adapters own whether they reuse a run-local parse, parse a
    file, or call a semantic worker.
    """

    cache: dict[str, SignatureAnalysis] = {}

    def hydrate(members: Sequence[SignatureAnalysis]) -> list[SignatureAnalysis]:
        pending: dict[str, SignatureAnalysis] = {}
        for member in members:
            key = signature_analysis_key(member)
            if key not in cache:
                pending[key] = member
        if pending:
            cache.update(_hydrate_relation_features(pending, context))
        return [cache[signature_analysis_key(member)] for member in members]

    return hydrate


def _hydrate_relation_features(
    signatures: Mapping[str, SignatureAnalysis],
    hydration: _RelationHydrationContext,
) -> dict[str, SignatureAnalysis]:
    plans: dict[str, _RelationDetailHydrationPlan] = {}
    hydrated: dict[str, SignatureAnalysis] = {}
    for key, signature in signatures.items():
        if _has_relation_detail(signature.features):
            hydrated[key] = signature
            continue
        if plan := _relation_detail_plan(signature, hydration):
            plans[key] = plan
        else:
            hydrated[key] = signature
    persistent_cache = hydration.caches.persistent if hydration.caches is not None else None
    if persistent_cache is not None:
        cached_features = cached_relation_detail_feature_map(
            persistent_cache,
            {
                plan.signature.core.signature_id: plan.cache_key
                for plan in plans.values()
                if plan.cache_key
            },
        )
        for key, plan in plans.items():
            if features := cached_features.get(plan.signature.core.signature_id):
                hydrated[key] = replace(plan.signature, features=features)
    features_by_cache_key: dict[str, SignatureAnalysisFeatures] = {}
    for key, plan in plans.items():
        if key in hydrated:
            continue
        features = _hydrate_relation_detail(plan, hydration)
        hydrated[key] = replace(plan.signature, features=features)
        if plan.cache_key:
            features_by_cache_key[plan.cache_key] = features
    if persistent_cache is not None and features_by_cache_key:
        store_relation_detail_feature_map(persistent_cache, features_by_cache_key)
    return hydrated


def _relation_detail_plan(
    signature: SignatureAnalysis,
    hydration: _RelationHydrationContext,
) -> _RelationDetailHydrationPlan | None:
    core = signature.core
    function = hydration.function_by_anchor.get((core.file, core.start_line, core.symbol))
    file_record = hydration.facts.records_by_path.get(core.file)
    if file_record is None:
        return None
    adapter = _adapter_for_language(hydration.registry, core.language)
    if adapter is None:
        return None
    provider = relation_detail_provider(adapter)
    if provider is None:
        return None
    cache_key = ""
    if hydration.caches is not None and function is not None:
        cache_key = relation_detail_cache_key(
            relation_detail_identity(
                signature,
                file_record=file_record,
                function=function,
                adapter_id=adapter.adapter_id.value,
            )
        )
    return _RelationDetailHydrationPlan(
        signature=signature,
        file_record=file_record,
        function=function,
        provider=provider,
        cache_key=cache_key,
    )


def _hydrate_relation_detail(
    plan: _RelationDetailHydrationPlan,
    hydration: _RelationHydrationContext,
) -> SignatureAnalysisFeatures:
    core = plan.signature.core
    context = language_context(
        hydration.repo_root,
        core.file,
        plan.file_record,
        hydration.run_cache,
    )
    return plan.provider.hydrate_relation_detail(
        RelationDetailRequest(
            context=context,
            signature=plan.signature,
            function=plan.function,
        )
    )


def _adapter_for_language(registry: LanguageRegistry, language: str) -> LanguageAdapter | None:
    return registry.adapter_for_language(language) or registry.adapter_for_language(
        language.title()
    )


def _has_relation_detail(features: SignatureAnalysisFeatures) -> bool:
    return bool(
        features.graph_features
        or features.literal_shapes
        or features.receiver_shapes
        or features.parameter_features
        or features.normalization_transform_tokens
        or features.statement_arg_reads
        or features.call_fingerprints
    )


__all__ = [
    "SignatureArtifacts",
    "build_signature_artifacts",
]
