from __future__ import annotations

from dataclasses import MISSING, fields
from typing import Any, cast

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


def signature_analyses_from_records(records: list[SignatureRecord]) -> list[SignatureAnalysis]:
    return [signature_analysis_from_record(record) for record in records]


def signature_core_cache_payload(
    records: list[SignatureAnalysis],
) -> tuple[SignatureCore, ...]:
    """Return the hot persistent signature-cache form.

    This blob is intentionally limited to identity, shape, and cheap structural
    signals. Analysis features and output-only detail are cached separately so
    later pipeline stages can avoid hydrating them when they are not needed.
    """

    return tuple(record.core for record in records)


def signature_features_cache_payload(
    records: list[SignatureAnalysis],
) -> tuple[SignatureAnalysisFeatures, ...]:
    return tuple(record.features for record in records)


def signature_output_cache_payload(
    records: list[SignatureAnalysis],
) -> tuple[SignatureOutputDetail, ...]:
    return tuple(record.output for record in records)


def signature_cores_from_cache_value(value: object) -> list[SignatureCore] | None:
    return _cache_items(value, SignatureCore)


def signature_features_from_cache_value(
    value: object,
) -> list[SignatureAnalysisFeatures] | None:
    return _cache_items(value, SignatureAnalysisFeatures)


def signature_output_from_cache_value(value: object) -> list[SignatureOutputDetail] | None:
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
    if not (len(core_items) == len(feature_items) == len(output_items)):
        return None
    return tuple(
        SignatureAnalysis(core=core, features=feature, output=output)
        for core, feature, output in zip(core_items, feature_items, output_items, strict=True)
    )


def _cache_items[T](value: object, item_type: type[T]) -> list[T] | None:
    if not isinstance(value, list | tuple):
        return None
    if not all(isinstance(item, item_type) for item in value):
        return None
    items = [_with_dataclass_defaults(item, item_type) for item in value]
    return None if any(item is None for item in items) else cast("list[T]", items)


def _with_dataclass_defaults[T](item: T, item_type: type[T]) -> T | None:
    """Rehydrate old cached dataclasses after optional fields are added."""

    if not hasattr(item_type, "__dataclass_fields__"):
        return item
    values: dict[str, Any] = {}
    for field in fields(cast("Any", item_type)):
        if hasattr(item, field.name):
            values[field.name] = getattr(item, field.name)
        elif field.default is not MISSING:
            values[field.name] = field.default
        elif field.default_factory is not MISSING:
            values[field.name] = cast("Any", field.default_factory)()
        else:
            return None
    return item_type(**values)


__all__ = [
    "SIGNATURE_CORE_CACHE_RECORD_SCHEMA",
    "SIGNATURE_FEATURES_CACHE_RECORD_SCHEMA",
    "SIGNATURE_OUTPUT_CACHE_RECORD_SCHEMA",
    "signature_analyses_from_cache_values",
    "signature_analyses_from_records",
    "signature_core_cache_payload",
    "signature_cores_from_cache_value",
    "signature_features_cache_payload",
    "signature_features_from_cache_value",
    "signature_output_cache_payload",
    "signature_output_from_cache_value",
]
