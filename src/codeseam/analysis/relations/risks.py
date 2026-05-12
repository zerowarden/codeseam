from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path, PurePosixPath

from codeseam.analysis.assessment import AbstractionRisk
from codeseam.analysis.relations.models import (
    CALLSITE_EVIDENCE_KINDS,
    AbstractionKind,
    EvidenceKind,
    RelationMemberContext,
    RiskKind,
)
from codeseam.analysis.relations.policy import (
    BOUNDARY_TOKENS,
    RELATION_ASSESSMENT_POLICY,
)
from codeseam.analysis.repository.classification import classify_path
from codeseam.platform import cached_identifier_tokens

STOP_TOKENS = {"get", "set", "make", "build", "create", "new"}
SOURCE_ROOT_PARTS = frozenset({"src", "lib", "source"})
TEST_ROOT_PARTS = frozenset({"test", "tests"})
LAYER_PARTS = 2


def abstraction_risks(
    members: Sequence[RelationMemberContext],
    evidence_kinds: Sequence[str],
) -> tuple[AbstractionRisk, ...]:
    risks: list[AbstractionRisk] = []
    if any(
        len(member.parameters) >= RELATION_ASSESSMENT_POLICY.many_parameter_threshold
        for member in members
    ):
        risks.append(
            risk(RiskKind.MANY_PARAMETERS, "Candidate abstraction may require many parameters.")
        )
    if vocabulary_mismatch(members):
        risks.append(risk(RiskKind.VOCABULARY_MISMATCH, "Members use different symbol vocabulary."))
    if len(layers(members)) > 1:
        risks.append(risk(RiskKind.LAYER_MISMATCH, "Members span different architectural layers."))
    if EvidenceKind.SIGNATURE_SHAPE_CLUSTER in evidence_kinds and len(evidence_kinds) == 1:
        risks.append(
            risk(RiskKind.SMALL_COMMONALITY, "Only weak signature-shape commonality is visible.")
        )
    if len({member.caveats for member in members}) > 1:
        risks.append(
            risk(
                RiskKind.ERROR_SEMANTICS_MISMATCH,
                "Members have different caveat or fallback evidence.",
            )
        )
    if boundary_mismatch(members):
        risks.append(
            risk(RiskKind.BOUNDARY_MISMATCH, "Boundary-sensitive and ordinary members are mixed.")
        )
    if any(is_test_member(member) for member in members) and len(roles(members)) > 1:
        risks.append(risk(RiskKind.TEST_SEMANTICS_MISMATCH, "Test and non-test members are mixed."))
    return tuple(risks)


def abstraction_kind(evidence_kinds: Sequence[str], risks: Sequence[AbstractionRisk]) -> str:
    risk_values = {risk.kind for risk in risks}
    has_callsite = any(kind in CALLSITE_EVIDENCE_KINDS for kind in evidence_kinds)
    high_risk = bool(
        risk_values
        & {
            RiskKind.LAYER_MISMATCH,
            RiskKind.VOCABULARY_MISMATCH,
            RiskKind.TEST_SEMANTICS_MISMATCH,
        }
    )
    kind: str = AbstractionKind.TRACK_ONLY
    if not high_risk or has_callsite:
        kind = _evidence_abstraction_kind(evidence_kinds)
    return kind


def _evidence_abstraction_kind(evidence_kinds: Sequence[str]) -> str:
    if EvidenceKind.CALLSITE_REGISTERED in evidence_kinds:
        return AbstractionKind.REGISTRY_DISPATCH
    if EvidenceKind.CALLSITE_PIPELINE in evidence_kinds:
        return AbstractionKind.PIPELINE_TEMPLATE
    if EvidenceKind.CALLABLE_FACTORY in evidence_kinds:
        return AbstractionKind.COMPILER_FACTORY
    if {
        EvidenceKind.STRUCTURAL_DUPLICATE,
        EvidenceKind.ARGUMENT_NORMALIZATION_WRAPPER,
    } & set(evidence_kinds):
        return AbstractionKind.EXTRACT_HELPER
    return AbstractionKind.TRACK_ONLY


def confidence_for(
    evidence_kinds: Sequence[str],
    risks: Sequence[AbstractionRisk],
    *,
    base: float = 0.35,
) -> float:
    score = base
    if EvidenceKind.CALLABLE_FACTORY in evidence_kinds:
        score += 0.05
    if any(kind in CALLSITE_EVIDENCE_KINDS for kind in evidence_kinds):
        score += 0.07
    if EvidenceKind.STRUCTURAL_DUPLICATE in evidence_kinds:
        score += 0.18
    if EvidenceKind.ARGUMENT_NORMALIZATION_WRAPPER in evidence_kinds:
        score += 0.12
    score -= min(0.18, 0.03 * len(risks))
    return round(max(0.15, min(0.85, score)), 4)


def risk(kind: str, message: str) -> AbstractionRisk:
    return AbstractionRisk(kind=kind, message=message)


def vocabulary_mismatch(members: Sequence[RelationMemberContext]) -> bool:
    token_sets = [tokens(member.symbol) for member in members]
    token_sets = [tokens for tokens in token_sets if tokens]
    if len(token_sets) < RELATION_ASSESSMENT_POLICY.min_vocabulary_members:
        return False
    common = set.intersection(*token_sets)
    return not common and len({tuple(sorted(tokens)) for tokens in token_sets}) > 1


def boundary_mismatch(members: Sequence[RelationMemberContext]) -> bool:
    flags = [
        bool(tokens(member.symbol) & BOUNDARY_TOKENS) or bool(tokens(member.file) & BOUNDARY_TOKENS)
        for member in members
    ]
    return any(flags) and not all(flags)


def layers(members: Sequence[RelationMemberContext]) -> set[str]:
    return {layer_path(member.file) for member in members if member.file}


def layer_path(path: str) -> str:
    parts = PurePosixPath(path).parts
    if not parts:
        return ""
    root = parts[0].lower()
    if root in TEST_ROOT_PARTS:
        return "tests"
    if root in SOURCE_ROOT_PARTS:
        return _layer_prefix(parts[1:], fallback=parts[0])
    return _layer_prefix(parts, fallback=parts[0])


def _layer_prefix(parts: tuple[str, ...], *, fallback: str) -> str:
    if len(parts) < LAYER_PARTS:
        return fallback
    return "/".join(parts[:LAYER_PARTS])


def roles(members: Sequence[RelationMemberContext]) -> set[str]:
    return {role for member in members if (role := member_role(member))}


def member_role(member: RelationMemberContext) -> str:
    role = member.role.lower()
    if role:
        return role
    return "test" if is_test_member(member) else ""


def is_test_member(member: RelationMemberContext) -> bool:
    role = member.role.lower()
    if role in {"test", "tests", "unit_test", "integration_test"}:
        return True
    return classify_path(Path(member.file)).is_test


def tokens(value: str) -> set[str]:
    return {token for token in cached_identifier_tokens(value) if token not in STOP_TOKENS}
