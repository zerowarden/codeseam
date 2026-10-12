from __future__ import annotations

import hashlib
from dataclasses import replace

from codeseam.analysis.findings.models import Finding
from codeseam.platform import Json, qualified_symbol, text

TARGET_ID_HEX_LENGTH = 12


def with_target_identity(target: Finding, *, positional: bool = False) -> Finding:
    identity_hash = target_identity_hash(target, positional=positional)
    return replace(
        target,
        target_id=target_id_for_hash(identity_hash),
        identity_hash=identity_hash,
    )


def target_identity_hash(target: Finding, *, positional: bool = False) -> str:
    """Hash what a target is about: its type and its members.

    Verdicts (action, evidence, relation and clone kinds, tier) are left out,
    so a target keeps its ID when its assessment changes. Members are named by
    file and qualified symbol, without line numbers, so IDs survive edits
    elsewhere in a file. ``positional`` adds start lines for the rare targets
    that names alone cannot tell apart, such as two module-level functions
    with one name.
    """

    parts = [
        ("target_type", target.target_type.value),
        ("members", "\x1f".join(_members(target, positional=positional))),
    ]
    payload = "\x1e".join(f"{key}={value}" for key, value in parts)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return "sha256:" + digest


def target_id_for_hash(identity_hash: str) -> str:
    return "rt_" + identity_hash.removeprefix("sha256:")[:TARGET_ID_HEX_LENGTH]


def primary_action(target: Finding | Json) -> str:
    if isinstance(target, dict):
        summary_payload = target.get("refactor_action_summary", {})
        return (
            text(summary_payload.get("primary_action")) if isinstance(summary_payload, dict) else ""
        )
    summary = target.refactor_action_summary
    if summary is None or not summary.has_actions:
        return ""
    return summary.primary_action.value if summary.primary_action else ""


def _members(target: Finding, *, positional: bool) -> list[str]:
    members = []
    for location in target.locations:
        line = str(location.start_line) if positional or not location.symbol else ""
        if location.file:
            symbol = qualified_symbol(location.symbol, location.container)
            members.append("::".join((location.file, symbol, location.source, location.kind, line)))
    return sorted(set(members))


__all__ = [
    "target_id_for_hash",
    "target_identity_hash",
    "with_target_identity",
]
