from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from codeseam.analysis import (
    FileRecord,
    FunctionRecord,
    PolicyConstant,
    SignatureAnalysis,
    SignatureAnalysisFeatures,
    SignatureCore,
    SignatureOutputDetail,
    function_cache_payload,
    functions_from_cache_value,
)
from codeseam.cache.context import AnalysisCacheContext
from codeseam.cache.keys import cache_key, language_analysis_cache_key
from codeseam.cache.main import CacheCodec
from codeseam.cache.signatures import (
    SIGNATURE_CORE_CACHE_RECORD_SCHEMA,
    SIGNATURE_FEATURES_CACHE_RECORD_SCHEMA,
    SIGNATURE_OUTPUT_CACHE_RECORD_SCHEMA,
    signature_analyses_from_cache_values,
    signature_core_cache_payload,
    signature_cores_from_cache_value,
    signature_features_cache_payload,
    signature_features_from_cache_value,
    signature_output_cache_payload,
    signature_output_from_cache_value,
)
from codeseam.version import FUNCTION_CACHE_RECORD_SCHEMA, POLICY_CONSTANT_CACHE_RECORD_SCHEMA


class _LanguageAnalysisIdentity(Protocol):
    @property
    def language(self) -> str: ...

    @property
    def relative_path(self) -> str: ...

    @property
    def role(self) -> str: ...


@dataclass(frozen=True)
class FileAnalysisCacheResult:
    functions: tuple[FunctionRecord, ...] | None
    signatures: tuple[SignatureAnalysis, ...] | None
    policy_constants: tuple[PolicyConstant, ...] | None

    @property
    def complete(self) -> bool:
        return (
            self.functions is not None
            and self.signatures is not None
            and self.policy_constants is not None
        )


@dataclass(frozen=True)
class _FileCacheCodec[T](CacheCodec[T]):
    namespace: str
    dump_value: Callable[[T], object]
    load_value: Callable[[object], T | None]

    def dump(self, value: T) -> object:
        return self.dump_value(value)

    def load(self, value: object) -> T | None:
        return self.load_value(value)


@dataclass(frozen=True)
class _SignatureCacheComponent[T](CacheCodec[tuple[T, ...]]):
    namespace: str
    schema_version: str
    payload: Callable[[list[SignatureAnalysis]], tuple[T, ...]]
    restore: Callable[[object], list[T] | None]

    def dump(self, value: tuple[T, ...]) -> object:
        return value

    def load(self, value: object) -> tuple[T, ...] | None:
        items = self.restore(value)
        return tuple(items) if items is not None else None


_FUNCTIONS_CACHE = _FileCacheCodec[tuple[FunctionRecord, ...]](
    namespace="functions",
    dump_value=function_cache_payload,
    load_value=functions_from_cache_value,
)
_POLICY_CONSTANTS_CACHE = _FileCacheCodec[tuple[PolicyConstant, ...]](
    namespace="policy_constants",
    dump_value=lambda value: value,
    load_value=lambda value: (
        value
        if isinstance(value, tuple) and all(isinstance(item, PolicyConstant) for item in value)
        else None
    ),
)
_CORE_CACHE = _SignatureCacheComponent[SignatureCore](
    namespace="signature_cores",
    schema_version=SIGNATURE_CORE_CACHE_RECORD_SCHEMA,
    payload=signature_core_cache_payload,
    restore=signature_cores_from_cache_value,
)
_FEATURE_CACHE = _SignatureCacheComponent[SignatureAnalysisFeatures](
    namespace="signature_features",
    schema_version=SIGNATURE_FEATURES_CACHE_RECORD_SCHEMA,
    payload=signature_features_cache_payload,
    restore=signature_features_from_cache_value,
)
_OUTPUT_CACHE = _SignatureCacheComponent[SignatureOutputDetail](
    namespace="signature_output",
    schema_version=SIGNATURE_OUTPUT_CACHE_RECORD_SCHEMA,
    payload=signature_output_cache_payload,
    restore=signature_output_from_cache_value,
)


def cached_file_analysis(
    context: _LanguageAnalysisIdentity,
    file_record: FileRecord,
    adapter_id: str,
    *,
    supports_policy_constants: bool,
    caches: AnalysisCacheContext,
) -> FileAnalysisCacheResult:
    return FileAnalysisCacheResult(
        functions=caches.cache(_FUNCTIONS_CACHE).get(
            _function_cache_key(context, file_record, adapter_id)
        ),
        signatures=_cached_signatures(context, file_record, adapter_id, caches),
        policy_constants=_cached_policy_constants(
            context,
            file_record,
            adapter_id,
            supports_policy_constants,
            caches,
        ),
    )


def store_file_analysis(
    context: _LanguageAnalysisIdentity,
    file_record: FileRecord,
    adapter_id: str,
    *,
    caches: AnalysisCacheContext,
    values: FileAnalysisCacheResult,
) -> None:
    if not caches.file_analysis_enabled:
        return
    if values.functions is not None:
        caches.cache(_FUNCTIONS_CACHE).set(
            _function_cache_key(context, file_record, adapter_id),
            values.functions,
        )
    if values.signatures is not None:
        _store_signatures(context, file_record, adapter_id, caches, values.signatures)
    if values.policy_constants is not None:
        caches.cache(_POLICY_CONSTANTS_CACHE).set(
            _policy_constant_cache_key(context, file_record, adapter_id),
            values.policy_constants,
        )


def _cached_signatures(
    context: _LanguageAnalysisIdentity,
    file_record: FileRecord,
    adapter_id: str,
    caches: AnalysisCacheContext,
) -> tuple[SignatureAnalysis, ...] | None:
    key_for = _signature_cache_key_factory(context, file_record, adapter_id)
    cores = caches.cache(_CORE_CACHE).get(key_for(_CORE_CACHE.schema_version))
    if cores is None:
        return None
    features = caches.cache(_FEATURE_CACHE).get(key_for(_FEATURE_CACHE.schema_version))
    outputs = caches.cache(_OUTPUT_CACHE).get(key_for(_OUTPUT_CACHE.schema_version))
    if features is None or outputs is None:
        return None
    return signature_analyses_from_cache_values(cores, features, outputs)


def _cached_policy_constants(
    context: _LanguageAnalysisIdentity,
    file_record: FileRecord,
    adapter_id: str,
    supported: bool,
    caches: AnalysisCacheContext,
) -> tuple[PolicyConstant, ...] | None:
    if not supported:
        return ()
    return caches.cache(_POLICY_CONSTANTS_CACHE).get(
        _policy_constant_cache_key(context, file_record, adapter_id)
    )


def _store_signatures(
    context: _LanguageAnalysisIdentity,
    file_record: FileRecord,
    adapter_id: str,
    caches: AnalysisCacheContext,
    signatures: tuple[SignatureAnalysis, ...],
) -> None:
    signature_items = list(signatures)
    key_for = _signature_cache_key_factory(context, file_record, adapter_id)
    caches.cache(_CORE_CACHE).set(
        key_for(_CORE_CACHE.schema_version),
        _CORE_CACHE.payload(signature_items),
    )
    caches.cache(_FEATURE_CACHE).set(
        key_for(_FEATURE_CACHE.schema_version),
        _FEATURE_CACHE.payload(signature_items),
    )
    caches.cache(_OUTPUT_CACHE).set(
        key_for(_OUTPUT_CACHE.schema_version),
        _OUTPUT_CACHE.payload(signature_items),
    )


def _signature_cache_key_factory(
    context: _LanguageAnalysisIdentity,
    file_record: FileRecord,
    adapter_id: str,
) -> Callable[[str], str]:
    def key_for(schema_version: str) -> str:
        return _language_analysis_key(
            "signatures",
            context,
            file_record,
            adapter_id,
            schema_version,
        )

    return key_for


def _function_cache_key(
    context: _LanguageAnalysisIdentity,
    file_record: FileRecord,
    adapter_id: str,
) -> str:
    return _language_analysis_key(
        "functions",
        context,
        file_record,
        adapter_id,
        FUNCTION_CACHE_RECORD_SCHEMA,
    )


def _policy_constant_cache_key(
    context: _LanguageAnalysisIdentity,
    file_record: FileRecord,
    adapter_id: str,
) -> str:
    return _language_analysis_key(
        "policy_constants",
        context,
        file_record,
        adapter_id,
        POLICY_CONSTANT_CACHE_RECORD_SCHEMA,
    )


def _language_analysis_key(
    kind: str,
    context: _LanguageAnalysisIdentity,
    file_record: FileRecord,
    adapter_id: str,
    schema_version: str,
) -> str:
    payload = language_analysis_cache_key(
        kind,
        context,
        file_record,
        adapter_id,
    )
    payload["record_cache_schema"] = schema_version
    return cache_key(payload)


__all__ = ["FileAnalysisCacheResult", "cached_file_analysis", "store_file_analysis"]
