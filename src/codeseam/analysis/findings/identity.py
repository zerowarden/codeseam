from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import overload

from codeseam.analysis.findings.models import Finding
from codeseam.platform import Json, json_text_keys, text, text_list

TARGET_ID_HEX_LENGTH = 12


@overload
def with_target_identity(target: Finding) -> Finding: ...


@overload
def with_target_identity(target: Json) -> Json: ...


def with_target_identity(target: Finding | Json) -> Finding | Json:
    identity_hash = target_identity_hash(target)
    if isinstance(target, dict):
        return {
            **target,
            "target_id": target_id_for_hash(identity_hash),
            "identity_hash": identity_hash,
        }
    return replace(
        target,
        target_id=target_id_for_hash(identity_hash),
        identity_hash=identity_hash,
    )


def target_identity_hash(target: Finding | Json) -> str:
    if isinstance(target, dict):
        return _payload_identity_hash(target)
    parts = [
        ("target_type", target.target_type.value),
        ("canonical_shape", _canonical_shape(target)),
        ("primary_action", primary_action(target)),
        ("evidence_classes", "\x1f".join(sorted(target.evidence_classes))),
        ("evidence_kinds", "\x1f".join(sorted(target.evidence_kinds))),
        ("relation_kinds", "\x1f".join(_metric_keys(target, "relation_kind_counts"))),
        ("clone_types", "\x1f".join(_metric_keys(target, "clone_type_counts"))),
        ("members", "\x1f".join(_members(target))),
    ]
    payload = "\x1e".join(f"{key}={value}" for key, value in parts)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return "sha256:" + digest


def target_id_for_hash(identity_hash: str) -> str:
    return "rt_" + identity_hash.removeprefix("sha256:")[:TARGET_ID_HEX_LENGTH]


def _payload_identity_hash(target: Json) -> str:
    parts = [
        ("target_type", text(target.get("target_type"))),
        ("canonical_shape", _payload_canonical_shape(target)),
        ("primary_action", _payload_primary_action(target)),
        ("evidence_classes", "\x1f".join(sorted(text_list(target.get("evidence_classes"))))),
        ("evidence_kinds", "\x1f".join(sorted(text_list(target.get("evidence_kinds"))))),
        ("relation_kinds", "\x1f".join(_payload_metric_keys(target, "relation_kind_counts"))),
        ("clone_types", "\x1f".join(_payload_metric_keys(target, "clone_type_counts"))),
        ("members", "\x1f".join(_payload_members(target))),
    ]
    payload = "\x1e".join(f"{key}={value}" for key, value in parts)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return "sha256:" + digest


def _payload_canonical_shape(target: Json) -> str:
    metrics = target.get("metrics", {})
    if isinstance(metrics, dict):
        shape = text(metrics.get("canonical_shape"))
        if shape:
            return shape
    return " ".join(text(target.get("title")).split())


def _payload_primary_action(target: Json) -> str:
    summary = target.get("refactor_action_summary", {})
    if isinstance(summary, dict):
        return text(summary.get("primary_action"))
    return ""


def _payload_metric_keys(target: Json, key: str) -> list[str]:
    metrics = target.get("metrics", {})
    return json_text_keys(metrics, key) if isinstance(metrics, dict) else []


def _payload_members(target: Json) -> list[str]:
    locations = target.get("locations", [])
    if not isinstance(locations, list):
        return []
    members = []
    for location in locations:
        if not isinstance(location, dict):
            continue
        file_path = text(location.get("file"))
        symbol = text(location.get("symbol"))
        source = text(location.get("source"))
        kind = text(location.get("kind"))
        line = "" if symbol else text(location.get("start_line"))
        if file_path:
            members.append("::".join((file_path, symbol, source, kind, line)))
    return sorted(set(members))


def _canonical_shape(target: Finding) -> str:
    shape = target.metrics.canonical_shape
    if shape:
        return shape
    return " ".join(target.title.split())


def primary_action(target: Finding | Json) -> str:
    if isinstance(target, dict):
        return _payload_primary_action(target)
    summary = target.refactor_action_summary
    if summary is None or not summary.has_actions:
        return ""
    return summary.primary_action.value if summary.primary_action else ""


def _metric_keys(target: Finding, key: str) -> list[str]:
    if key == "relation_kind_counts":
        values = target.metrics.relation_kind_counts or {}
    elif key == "clone_type_counts":
        values = target.metrics.clone_type_counts or {}
    else:
        values = {}
    return sorted(str(value) for value in values)


def _members(target: Finding) -> list[str]:
    members = []
    for location in target.locations:
        file_path = location.file
        symbol = location.symbol
        source = location.source
        kind = location.kind
        line = "" if symbol else str(location.start_line)
        if file_path:
            members.append("::".join((file_path, symbol, source, kind, line)))
    return sorted(set(members))


__all__ = [
    "target_id_for_hash",
    "target_identity_hash",
    "with_target_identity",
]
