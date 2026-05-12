from __future__ import annotations

import re

from codeseam.analysis.relations.models import MemberFeatures

ARG_ROLE_RE = re.compile(r"ARG\d+")
MAX_CONTROL_CALL_SHINGLES = 16


def structural_shingles(features: MemberFeatures) -> frozenset[str]:
    """Return cheap, language-neutral structural shingles for candidate discovery.

    Shingles deliberately use normalized operation categories rather than raw
    source text or symbol names. They are used before expensive relation scoring,
    so they must stay deterministic, compact, and cheap to compute.
    """

    statements = tuple(_statement_shape(statement) for statement in features.statements)
    calls = tuple(target for call in features.calls if (target := _call_target(call)))
    shingles: set[str] = set()
    shingles.update(f"STMT:{statement}" for statement in statements if statement)
    shingles.update(
        f"BIGRAM:{left}->{right}"
        for left, right in zip(statements, statements[1:], strict=False)
        if left and right
    )
    shingles.update(f"CALL:{call}" for call in calls)
    shingles.update(_dataflow_shingles(features, statements))
    shingles.update(_control_call_shingles(features, calls))
    return frozenset(shingles)


def _statement_shape(statement: str) -> str:
    parts = [part for part in statement.split(":") if part]
    if not parts:
        return ""
    head = parts[0]
    detail = _generic_role(parts[1]) if len(parts) > 1 else ""
    return f"{head}:{detail}" if detail else head


def _call_target(call: str) -> str:
    return call.split("(args=", 1)[0].strip()


def _dataflow_shingles(
    features: MemberFeatures,
    statements: tuple[str, ...],
) -> set[str]:
    shingles: set[str] = set()
    for index, roles in features.statement_arg_reads:
        if index < 0 or index >= len(statements):
            continue
        target = _flow_target(statements[index])
        if not target:
            continue
        shingles.update(f"FLOW:{_generic_role(role)}->{target}" for role in roles)
    return shingles


def _control_call_shingles(
    features: MemberFeatures,
    calls: tuple[str, ...],
) -> set[str]:
    shingles: set[str] = set()
    for control in features.control_vector:
        if not control:
            continue
        for call in calls[:MAX_CONTROL_CALL_SHINGLES]:
            shingles.add(f"CTRL_CALL:{control}|CALL:{call}")
    return shingles


def _flow_target(statement: str) -> str:
    if "CALL" in statement:
        return "CALL"
    if statement.startswith("RETURN"):
        return "RETURN"
    if statement.startswith("ASSIGN"):
        return "ASSIGN"
    return ""


def _generic_role(value: str) -> str:
    return ARG_ROLE_RE.sub("ARG", value)


__all__ = ["structural_shingles"]
