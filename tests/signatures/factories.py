from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from helpers import file_record as _file_record

from codeseam.analysis import (
    Cluster,
    Clusters,
    DataflowGraph,
    LanguageFamily,
    RepositoryFacts,
    RepositoryScan,
    SignatureCore,
    SignatureRecord,
    SignatureTypeSource,
    adapter_id,
    build_repository_facts,
    language_family,
    signature_core_from_record,
)
from codeseam.cache import AnalysisCacheContext, LanguageRunCache, PersistentCache
from codeseam.config import Config, load_config
from codeseam.output.serializers.signatures import signature_clusters_payload
from codeseam.pipeline.signatures import SignatureArtifacts, build_signature_artifacts

FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "signatures"


def cluster_payloads(clusters: tuple[Cluster, ...]) -> list[dict[str, Any]]:
    return cast(
        list[dict[str, Any]],
        signature_clusters_payload(
            Clusters(
                clusters=tuple(clusters),
                policy_constant_clusters=(),
            )
        )["clusters"],
    )


def signature_artifact_payload(artifacts: SignatureArtifacts) -> dict[str, Any]:
    return signature_clusters_payload(artifacts.clusters)


def fixture_cluster_payloads(path_roles: list[tuple[str, str]]) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], fixture_payload(path_roles)["clusters"])


def fixture_payload(path_roles: list[tuple[str, str]]) -> dict[str, Any]:
    return signature_artifact_payload(fixture_artifacts(path_roles))


def fixture_artifacts(
    path_roles: list[tuple[str, str]],
    cache: AnalysisCacheContext | None = None,
) -> SignatureArtifacts:
    return signature_artifacts(load_config(FIXTURE_ROOT), path_roles, cache)


def repository_facts(path_roles: list[tuple[str, str]]) -> RepositoryFacts:
    return build_repository_facts(
        RepositoryScan(
            records=[_file_record(path, role=role) for path, role in path_roles],
            selected_paths=[path for path, _role in path_roles],
        )
    )


def signature_artifacts(
    config: Config,
    path_roles: list[tuple[str, str]],
    cache: AnalysisCacheContext | None = None,
) -> SignatureArtifacts:
    return build_signature_artifacts(config, repository_facts(path_roles), [], cache)


def audit_cache(cache: PersistentCache) -> AnalysisCacheContext:
    return AnalysisCacheContext(
        persistent=cache,
        file_analysis_enabled=True,
        relation_pair_enabled=True,
        language=LanguageRunCache(),
    )


def signature(  # noqa: PLR0913
    signature_id: str,
    language: str,
    file_path: str,
    symbol: str,
    shape: str,
    shape_hash: str,
    *,
    family: str | None = None,
    adapter: str | None = None,
    role: str = "source",
) -> SignatureCore:
    return signature_core_from_record(
        signature_record(
            signature_id,
            language,
            file_path,
            symbol,
            shape,
            shape_hash,
            family=family,
            adapter=adapter,
            role=role,
        )
    )


def signature_with_body_hash(  # noqa: PLR0913
    signature_id: str,
    file_path: str,
    symbol: str,
    shape: str,
    shape_hash: str,
    body_shape_hash: str,
) -> SignatureCore:
    item = signature(signature_id, "python", file_path, symbol, shape, shape_hash)
    return replace(item, body_shape_hash=body_shape_hash)


def signature_record(  # noqa: PLR0913
    signature_id: str,
    language: str,
    file_path: str,
    symbol: str,
    shape: str,
    shape_hash: str,
    *,
    family: str | None = None,
    adapter: str | None = None,
    role: str = "source",
) -> SignatureRecord:
    return SignatureRecord(
        schema_version="codeseam.signature.v1",
        signature_id=signature_id,
        function_id=None,
        language=language,
        language_family=language_family(family or language),
        adapter=adapter_id(adapter or ("python_ast" if language == "python" else "unknown")),
        file=file_path,
        symbol=symbol,
        normalized_symbol=symbol,
        container=None,
        start_line=1,
        end_line=1,
        role=role,
        type_source=SignatureTypeSource.FALLBACK,
        parameters=["UNKNOWN"],
        return_type="UNKNOWN",
        raw_signature="",
        canonical_shape=shape,
        shape_hash=shape_hash,
        body_line_count=1,
        body_shape="",
        body_shape_hash="",
        body_tree=None,
        body_tree_node_count=0,
        statement_sequence=[],
        call_fingerprints=(),
        parameter_use_vectors={},
        parameter_default_roles={},
        local_dataflow_graph=DataflowGraph(),
        control_context_vector=[],
        caveats=[],
        non_claims=["Same signature shape does not imply same behavior."],
    )


def typescript_adapter_core_kwargs() -> dict[str, object]:
    return {
        "family": LanguageFamily.ECMASCRIPT_TYPESCRIPT,
        "adapter": "treesitter_ecmascript_typescript",
    }
