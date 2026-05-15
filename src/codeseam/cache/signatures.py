from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from codeseam.analysis import (
    SignatureAnalysis,
    SignatureAnalysisFeatures,
    SignatureCore,
    SignatureOutputDetail,
    SignatureRecord,
    signature_analysis_from_record,
)
from codeseam.version import (
    SIGNATURE_CORE_CACHE_RECORD_SCHEMA,
    SIGNATURE_FEATURES_CACHE_RECORD_SCHEMA,
    SIGNATURE_OUTPUT_CACHE_RECORD_SCHEMA,
)


def signature_analyses_from_records(
    records: Sequence[SignatureRecord],
) -> tuple[SignatureAnalysis, ...]:
    return tuple(signature_analysis_from_record(record) for record in records)


def signature_core_cache_payload(
    records: Sequence[SignatureAnalysis],
) -> tuple[SignatureCore, ...]:
    """Return the hot persistent signature-cache form.

    This blob is intentionally limited to identity, shape, and cheap structural
    signals. Analysis features and output-only detail are cached separately so
    later pipeline stages can avoid hydrating them when they are not needed.
    """

    return tuple(record.core for record in records)


def signature_features_cache_payload(
    records: Sequence[SignatureAnalysis],
) -> tuple[SignatureAnalysisFeatures, ...]:
    return tuple(record.features for record in records)


def signature_output_cache_payload(
    records: Sequence[SignatureAnalysis],
) -> tuple[SignatureOutputDetail, ...]:
    return tuple(record.output for record in records)


def signature_cores_from_cache_value(value: object) -> tuple[SignatureCore, ...] | None:
    return _cache_items(value, SignatureCore)


def signature_features_from_cache_value(
    value: object,
) -> tuple[SignatureAnalysisFeatures, ...] | None:
    return _cache_items(value, SignatureAnalysisFeatures)


def signature_output_from_cache_value(
    value: object,
) -> tuple[SignatureOutputDetail, ...] | None:
    return _cache_items(value, SignatureOutputDetail)


def signature_analyses_from_cache_values(
    cores: object,
    features: object,
    outputs: object,
) -> tuple[SignatureAnalysis, ...] | None:
    core_items = signature_cores_from_cache_value(cores)
    feature_items = signature_features_from_cache_value(features)
    output_items = signature_output_from_cache_value(outputs)
    if core_items is None or feature_items is None or output_items is None:
        return None
    return signature_analyses_from_cache_parts(core_items, feature_items, output_items)


def signature_analyses_from_cache_parts(
    cores: Sequence[SignatureCore],
    features: Sequence[SignatureAnalysisFeatures],
    outputs: Sequence[SignatureOutputDetail],
) -> tuple[SignatureAnalysis, ...] | None:
    if not (len(cores) == len(features) == len(outputs)):
        return None
    return tuple(
        SignatureAnalysis(core=core, features=feature, output=output)
        for core, feature, output in zip(cores, features, outputs, strict=True)
    )


def _cache_items[T](value: object, item_type: type[T]) -> tuple[T, ...] | None:
    if not isinstance(value, tuple):
        return None
    if not all(isinstance(item, item_type) for item in value):
        return None
    return cast("tuple[T, ...]", value)


__all__ = [
    "SIGNATURE_CORE_CACHE_RECORD_SCHEMA",
    "SIGNATURE_FEATURES_CACHE_RECORD_SCHEMA",
    "SIGNATURE_OUTPUT_CACHE_RECORD_SCHEMA",
    "signature_analyses_from_cache_parts",
    "signature_analyses_from_cache_values",
    "signature_analyses_from_records",
    "signature_core_cache_payload",
    "signature_cores_from_cache_value",
    "signature_features_cache_payload",
    "signature_features_from_cache_value",
    "signature_output_cache_payload",
    "signature_output_from_cache_value",
]
