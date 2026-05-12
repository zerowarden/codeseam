from __future__ import annotations

from codeseam.analysis.assessment.models import EvidenceSummary
from codeseam.analysis.findings import FindingMetrics
from codeseam.analysis.relations import CALLSITE_EVIDENCE_KINDS, EvidenceKind
from codeseam.analysis.relations.models import RelationPair

EVIDENCE_SIGNATURE_SHAPE = "signature_shape"
EVIDENCE_NAME_SIMILARITY = "name_similarity"
EVIDENCE_BODY_TREE_SIMILARITY = "body_tree_similarity"
EVIDENCE_STATEMENT_SEQUENCE_ALIGNMENT = "statement_sequence_alignment"
EVIDENCE_ANTI_UNIFICATION_TEMPLATE = "anti_unification_template"
EVIDENCE_CALL_FINGERPRINT_OVERLAP = "call_fingerprint_overlap"
EVIDENCE_PARAMETER_USE_SIMILARITY = "parameter_use_similarity"
EVIDENCE_LOCAL_DATAFLOW_SIMILARITY = "local_dataflow_similarity"
EVIDENCE_CONTROL_CONTEXT_SIMILARITY = "control_context_similarity"
EVIDENCE_SHARED_POLICY_LITERAL = "shared_policy_literal"
EVIDENCE_ARGUMENT_NORMALIZATION_WRAPPER = "argument_normalization_wrapper"
EVIDENCE_SEMANTIC_SHARED_CALL_TARGET = "semantic_shared_call_target"
EVIDENCE_SEMANTIC_OVERLOAD_BINDING = "semantic_overload_binding"
EVIDENCE_SEMANTIC_DECLARATION_SURFACE = "semantic_declaration_surface"
EVIDENCE_SEMANTIC_UNRESOLVED = "semantic_unresolved"
EVIDENCE_SEMANTIC_AMBIGUOUS_OWNERSHIP = "semantic_ambiguous_ownership"
EVIDENCE_INTRA_FUNCTION_DUPLICATE = "intra_function_duplicate"


def evidence_summary(
    *,
    metrics: FindingMetrics,
    evidence_kinds: tuple[str, ...],
    relation_pairs: tuple[RelationPair, ...],
    has_signature_overlap: bool,
) -> EvidenceSummary:
    classes: list[str] = []
    kinds = set(evidence_kinds)
    if has_signature_overlap or EvidenceKind.SIGNATURE_SHAPE_CLUSTER in kinds:
        classes.append(EVIDENCE_SIGNATURE_SHAPE)
    if EvidenceKind.POLICY_CONSTANT_DUPLICATE in kinds:
        classes.append(EVIDENCE_SHARED_POLICY_LITERAL)
    if EvidenceKind.ARGUMENT_NORMALIZATION_WRAPPER in kinds:
        classes.append(EVIDENCE_ARGUMENT_NORMALIZATION_WRAPPER)
    if (
        metrics.intra_function_duplicate_block_count
        or EvidenceKind.INTRA_FUNCTION_DUPLICATE in kinds
    ):
        classes.append(EVIDENCE_INTRA_FUNCTION_DUPLICATE)
    if metrics.max_name_similarity:
        classes.append(EVIDENCE_NAME_SIMILARITY)
    if metrics.max_tree_similarity or EvidenceKind.STRUCTURAL_DUPLICATE in kinds:
        classes.append(EVIDENCE_BODY_TREE_SIMILARITY)
    if metrics.structural_relation_pair_count:
        classes.append(EVIDENCE_STATEMENT_SEQUENCE_ALIGNMENT)
    if any(pair.anti_unification for pair in relation_pairs):
        classes.append(EVIDENCE_ANTI_UNIFICATION_TEMPLATE)
    if metrics.call_fingerprint_count or any(
        kind in CALLSITE_EVIDENCE_KINDS or kind == EvidenceKind.CALLABLE_FACTORY for kind in kinds
    ):
        classes.append(EVIDENCE_CALL_FINGERPRINT_OVERLAP)
    if any(pair.scores.parameter_use for pair in relation_pairs):
        classes.append(EVIDENCE_PARAMETER_USE_SIMILARITY)
    if any(pair.scores.graph for pair in relation_pairs):
        classes.append(EVIDENCE_LOCAL_DATAFLOW_SIMILARITY)
    if metrics.control_context_count:
        classes.append(EVIDENCE_CONTROL_CONTEXT_SIMILARITY)
    classes.extend(_semantic_evidence_classes(metrics))
    return EvidenceSummary.from_classes(tuple(classes))


def _semantic_evidence_classes(metrics: FindingMetrics) -> tuple[str, ...]:
    classes: list[str] = []
    semantic = metrics.semantic_evidence
    if semantic.shared_call_target_pair_count:
        classes.append(EVIDENCE_SEMANTIC_SHARED_CALL_TARGET)
    if semantic.same_overload_group_pair_count:
        classes.append(EVIDENCE_SEMANTIC_OVERLOAD_BINDING)
    if semantic.declaration_only_count:
        classes.append(EVIDENCE_SEMANTIC_DECLARATION_SURFACE)
    if semantic.unresolved_item_count:
        classes.append(EVIDENCE_SEMANTIC_UNRESOLVED)
    if semantic.ambiguous_ownership_count:
        classes.append(EVIDENCE_SEMANTIC_AMBIGUOUS_OWNERSHIP)
    return tuple(classes)


__all__ = [
    "EvidenceSummary",
    "EVIDENCE_ANTI_UNIFICATION_TEMPLATE",
    "EVIDENCE_ARGUMENT_NORMALIZATION_WRAPPER",
    "EVIDENCE_BODY_TREE_SIMILARITY",
    "EVIDENCE_CALL_FINGERPRINT_OVERLAP",
    "EVIDENCE_CONTROL_CONTEXT_SIMILARITY",
    "EVIDENCE_INTRA_FUNCTION_DUPLICATE",
    "EVIDENCE_LOCAL_DATAFLOW_SIMILARITY",
    "EVIDENCE_NAME_SIMILARITY",
    "EVIDENCE_PARAMETER_USE_SIMILARITY",
    "EVIDENCE_SEMANTIC_AMBIGUOUS_OWNERSHIP",
    "EVIDENCE_SEMANTIC_DECLARATION_SURFACE",
    "EVIDENCE_SEMANTIC_OVERLOAD_BINDING",
    "EVIDENCE_SEMANTIC_SHARED_CALL_TARGET",
    "EVIDENCE_SEMANTIC_UNRESOLVED",
    "EVIDENCE_SHARED_POLICY_LITERAL",
    "EVIDENCE_SIGNATURE_SHAPE",
    "EVIDENCE_STATEMENT_SEQUENCE_ALIGNMENT",
    "evidence_summary",
]
