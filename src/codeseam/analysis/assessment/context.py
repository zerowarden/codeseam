"""Classify low-information relation contexts before scoring the findings.

Signature clusters can contain real duplication, but they also contain repeated
boundaries that are intentionally similar: interface methods, generic
conversion boundaries, report sections, and shared lifecycle wrappers with
different payloads. These classifiers keep that context in the domain model so
scoring can downgrade noisy findings before JSON/report rendering.

The rules deliberately use language-neutral `SignatureCore` evidence and
semantic type classes. Language adapters may spell equivalent types differently
(`list[str]`, `Array<string>`, `Vec<String>`, `[String]`), so relation context
must not depend on one language's concrete type names.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from codeseam.analysis.assessment.definitions import EvidenceStrength, FindingVisibility, ReviewTier
from codeseam.analysis.assessment.models import ContextClassification
from codeseam.analysis.relations.models import (
    ActionKind,
    RelationKind,
    RelationPair,
)
from codeseam.analysis.signatures import (
    BoundarySpecificity,
    SignatureCore,
    SignatureTypeClass,
    SignatureTypeSource,
    classify_signature_type,
    collection_element_type_class,
)
from codeseam.platform import cached_identifier_tokens

MIN_CLASSIFIABLE_MEMBERS = 2
MIN_DISTINCT_CONTAINERS = 2
THIN_WRAPPER_MAX_LINES = 3
SUBSTANTIAL_TREE_SIMILARITY = 0.95
HIGH_NAME_SIMILARITY = 0.95
MIN_SHARED_LIFECYCLE_EDGE = 1
TINY_FUNCTION_STATEMENT_COUNT = 2
STABLE_STATEMENT_COUNT = 2
MIN_CORROBORATING_SIGNALS = 2
GENERIC_MAPPER_MIN_MEMBERS = 5
GENERIC_MAPPER_MIN_FILES = 4
GENERIC_PREDICATE_MIN_MEMBERS = 4
GENERIC_PREDICATE_MIN_FILES = 3
LOW_SPECIFICITY_PARAM_CLASSES = {
    SignatureTypeClass.UNKNOWN,
    SignatureTypeClass.OPAQUE,
    SignatureTypeClass.MAPPING,
}
LOW_SPECIFICITY_RETURN_CLASSES = {
    SignatureTypeClass.UNKNOWN,
    SignatureTypeClass.OPAQUE,
    SignatureTypeClass.MAPPING,
}


@dataclass(frozen=True, slots=True)
class _MemberContext:
    file: str
    symbol: str
    container: str
    parameters: tuple[str, ...]
    return_type: str
    type_source: SignatureTypeSource
    parameter_classes: tuple[SignatureTypeClass, ...]
    return_class: SignatureTypeClass
    body_line_count: int
    body_shape_hash: str
    statement_sequence: tuple[str, ...]
    call_tokens: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _ClassifierFeatures:
    same_module: bool
    boundary_specificity: BoundarySpecificity
    method_name_family: bool
    shared_call_fingerprint: bool
    substantial_shared_body: bool
    relation_kinds: frozenset[RelationKind]
    statement_count_max: int
    corroborating_signals: tuple[str, ...]


def classify_contexts(
    members: Sequence[SignatureCore],
    relation_pairs: Sequence[RelationPair],
    structural_pairs: Sequence[RelationPair],
) -> tuple[ContextClassification, ...]:
    """Return context labels that explain why a cluster may be low-value noise."""
    views = [_member_context(member) for member in members]
    if len(views) < MIN_CLASSIFIABLE_MEMBERS:
        return ()
    relation_items = list(relation_pairs)
    structural_items = list(structural_pairs)
    features = _classifier_features(views, relation_items)
    for classification in (
        _interface_contract(views, features, structural_items),
        _generic_mapper_boundary(views, features, relation_items),
        _generic_predicate_family(views, features, relation_items),
        _shared_lifecycle_different_payload(views, features, structural_items),
        _render_section_family(views, features, structural_items),
    ):
        if classification is not None:
            return (classification,)
    classifications = (_signature_only_boundary(views, features, structural_items),)
    return tuple(item for item in classifications if item is not None)


def _interface_contract(
    members: list[_MemberContext],
    features: _ClassifierFeatures,
    structural_pairs: list[RelationPair],
) -> ContextClassification | None:
    """Detect thin same-name methods across containers.

    These usually represent interface, protocol, or adapter contract methods.
    Their shape is repeated by design, so they should stay visible as sidecar
    evidence rather than become a primary refactor target.
    """
    if structural_pairs or not features.relation_kinds:
        return None
    if len(_symbols(members)) != 1 or len(_containers(members)) < MIN_DISTINCT_CONTAINERS:
        return None
    if max(member.body_line_count for member in members) > THIN_WRAPPER_MAX_LINES:
        return None
    if features.substantial_shared_body:
        return None
    return ContextClassification(
        kind="adapter_contract_method",
        context_tags=("interface_contract", "adapter_contract_method", "intentional_polymorphism"),
        visibility=FindingVisibility.SIDECAR_ONLY,
        summary_eligible=False,
        action=ActionKind.OBSERVE,
        refactor_value="none",
        refactor_safety="unsafe",
        review_tier=ReviewTier.OBSERVATION,
        evidence_strength=EvidenceStrength.WEAK,
        boundary_specificity=features.boundary_specificity,
        corroborating_signals=features.corroborating_signals,
        downgrade_reasons=(
            "Same method boundary appears across multiple containers.",
            "Bodies are thin delegated wrappers with no substantial duplicated implementation.",
            "Repeated shape is likely an intentional interface or adapter contract.",
        ),
    )


def _signature_only_boundary(
    members: list[_MemberContext],
    features: _ClassifierFeatures,
    structural_pairs: list[RelationPair],
) -> ContextClassification | None:
    """Detect generic boundaries supported only by weak signature evidence."""
    if not _is_signature_only_low_info(members, features, structural_pairs):
        return None
    return ContextClassification(
        kind="signature_only_boundary",
        context_tags=("generic_boundary", "signature_only", "low_specificity_boundary"),
        visibility=FindingVisibility.SIDECAR_ONLY,
        summary_eligible=False,
        action=ActionKind.OBSERVE,
        refactor_value="none",
        refactor_safety="unsafe",
        review_tier=ReviewTier.OBSERVATION,
        evidence_strength=EvidenceStrength.WEAK,
        boundary_specificity=features.boundary_specificity,
        corroborating_signals=features.corroborating_signals,
        downgrade_reasons=(
            f"Repeated shape has {features.boundary_specificity} boundary specificity.",
            "Members do not share enough name, call, or body evidence.",
            "Signature shape alone is not a refactor signal.",
        ),
    )


def _generic_mapper_boundary(
    members: list[_MemberContext],
    features: _ClassifierFeatures,
    relation_pairs: list[RelationPair],
) -> ContextClassification | None:
    """Detect broad object-to-object mapper families across unrelated modules.

    Python `Json`, TypeScript `Record<string, unknown>`, Swift
    `[String: Any]`, and Rust JSON/map values all represent low-specificity
    payload boundaries. Similar dict/map skeletons are common in output and
    adapter code, but the fields are usually local contracts rather than one
    reusable domain abstraction. Exact body matches are still allowed through:
    this classifier only downgrades wide, weak mapper families.
    """
    if not _is_wide_generic_mapper_family(members, features, relation_pairs):
        return None
    return ContextClassification(
        kind="generic_mapper_boundary",
        context_tags=("generic_boundary", "mapping_payload", "different_payload"),
        visibility=FindingVisibility.SIDECAR_ONLY,
        summary_eligible=False,
        action=ActionKind.OBSERVE,
        refactor_value="none",
        refactor_safety="unsafe",
        review_tier=ReviewTier.OBSERVATION,
        evidence_strength=EvidenceStrength.WEAK,
        boundary_specificity=features.boundary_specificity,
        corroborating_signals=features.corroborating_signals,
        downgrade_reasons=(
            "Members share a low-specificity object-to-object boundary.",
            "Examples span unrelated modules, so a common abstraction is not proven.",
            "Similar payload skeletons are local output contracts unless exact bodies match.",
        ),
    )


def _is_wide_generic_mapper_family(
    members: list[_MemberContext],
    features: _ClassifierFeatures,
    relation_pairs: list[RelationPair],
) -> bool:
    return (
        len(members) >= GENERIC_MAPPER_MIN_MEMBERS
        and len({member.file for member in members if member.file}) >= GENERIC_MAPPER_MIN_FILES
        and not features.same_module
        and not features.shared_call_fingerprint
        and features.boundary_specificity is BoundarySpecificity.LOW
        and _all_members(members, _low_specificity_mapper)
        and not any(pair.flags.body_hash_match for pair in relation_pairs)
    )


def _generic_predicate_family(
    members: list[_MemberContext],
    features: _ClassifierFeatures,
    relation_pairs: list[RelationPair],
) -> ContextClassification | None:
    """Detect broad boolean helper families with no shared operation.

    Boolean predicates over the same domain type often have the same signature
    and small control shape while answering unrelated questions. Exact clones
    still pass through; this classifier only caps broad, non-identical predicate
    families that lack shared call evidence.
    """

    if not _is_broad_generic_predicate_family(members, features, relation_pairs):
        return None
    return ContextClassification(
        kind="generic_predicate_family",
        context_tags=("generic_predicate", "different_predicate_intent"),
        visibility=FindingVisibility.SUMMARY_GROUPED,
        summary_eligible=True,
        action=ActionKind.RECORD_SHARED_CONCERN,
        refactor_value="low",
        refactor_safety="cautious",
        review_tier=ReviewTier.TRACKING_SIGNAL,
        evidence_strength=EvidenceStrength.MODERATE,
        boundary_specificity=features.boundary_specificity,
        corroborating_signals=features.corroborating_signals,
        downgrade_reasons=(
            "Members are boolean predicates over similar inputs.",
            "Predicate names and operations differ, so one abstraction is not proven.",
            "Track recurrence, but do not promote this generic predicate family to review.",
        ),
    )


def _is_broad_generic_predicate_family(
    members: list[_MemberContext],
    features: _ClassifierFeatures,
    relation_pairs: list[RelationPair],
) -> bool:
    return (
        len(members) >= GENERIC_PREDICATE_MIN_MEMBERS
        and len({member.file for member in members if member.file}) >= GENERIC_PREDICATE_MIN_FILES
        and all(member.return_class is SignatureTypeClass.BOOLEAN for member in members)
        and len({member.parameters for member in members}) == 1
        and not features.shared_call_fingerprint
        and not features.method_name_family
        and not any(pair.flags.body_hash_match for pair in relation_pairs)
    )


def _render_section_family(
    members: list[_MemberContext],
    features: _ClassifierFeatures,
    structural_pairs: list[RelationPair],
) -> ContextClassification | None:
    """Detect repeated collection-producing section renderers.

    The shared concern is often real, but whole-function consolidation is risky
    because each member tends to format a different payload. Stronger structural
    or call evidence can still promote it to grouped summary visibility.
    """
    if not _all_members(
        members,
        lambda member: member.return_class is SignatureTypeClass.COLLECTION,
    ):
        return None
    if not (features.same_module or features.method_name_family):
        return None
    enough_evidence = _corroborated_low_finding(
        features,
        has_structural_pairs=bool(structural_pairs),
    )
    return ContextClassification(
        kind="render_section_family",
        context_tags=("render_section_family", "bounded_section_lines"),
        visibility=(
            FindingVisibility.SUMMARY_GROUPED if enough_evidence else FindingVisibility.SIDECAR_ONLY
        ),
        summary_eligible=enough_evidence,
        action=ActionKind.RECORD_SHARED_CONCERN if enough_evidence else ActionKind.OBSERVE,
        refactor_value="low",
        refactor_safety="cautious",
        review_tier=ReviewTier.TRACKING_SIGNAL if enough_evidence else ReviewTier.OBSERVATION,
        evidence_strength=EvidenceStrength.MODERATE if enough_evidence else EvidenceStrength.WEAK,
        boundary_specificity=features.boundary_specificity,
        corroborating_signals=features.corroborating_signals,
        downgrade_reasons=(
            "Members render bounded text sections with similar boundaries.",
            "Fields and formatting differ, so a generic renderer is not yet justified.",
            "Prefer small local helpers only after additional body evidence appears.",
        ),
    )


def _shared_lifecycle_different_payload(
    members: list[_MemberContext],
    features: _ClassifierFeatures,
    structural_pairs: list[RelationPair],
) -> ContextClassification | None:
    """Detect common setup/teardown with divergent payload construction."""
    if structural_pairs or len(members) < MIN_CLASSIFIABLE_MEMBERS:
        return None
    if RelationKind.COMMON_WRAPPER_DIFFERENT_CORE not in features.relation_kinds:
        return None
    if not (_shared_builder_lifecycle(members) or _single_shared_value(members, _return_shape)):
        return None
    enough_evidence = _corroborated_low_finding(features, has_structural_pairs=False)
    return ContextClassification(
        kind="shared_lifecycle_different_payload",
        context_tags=("shared_lifecycle", "different_payload", "cautious_extraction"),
        visibility=(
            FindingVisibility.SUMMARY_GROUPED if enough_evidence else FindingVisibility.SIDECAR_ONLY
        ),
        summary_eligible=enough_evidence,
        action=ActionKind.RECORD_SHARED_CONCERN if enough_evidence else ActionKind.OBSERVE,
        refactor_value="low",
        refactor_safety="cautious",
        review_tier=ReviewTier.TRACKING_SIGNAL if enough_evidence else ReviewTier.OBSERVATION,
        evidence_strength=EvidenceStrength.MODERATE if enough_evidence else EvidenceStrength.WEAK,
        boundary_specificity=features.boundary_specificity,
        corroborating_signals=features.corroborating_signals,
        downgrade_reasons=(
            "Shared lifecycle exists, but payload construction differs.",
            "Whole-function consolidation would likely require many parameters.",
            "No stable generic builder abstraction is proven yet.",
        ),
    )


def _member_context(member: SignatureCore) -> _MemberContext:
    return _MemberContext(
        file=member.file,
        symbol=member.symbol,
        container=member.container or "",
        parameters=member.parameters,
        return_type=member.return_type,
        type_source=member.type_source,
        parameter_classes=tuple(classify_signature_type(item) for item in member.parameters),
        return_class=classify_signature_type(member.return_type),
        body_line_count=member.body_line_count,
        body_shape_hash=member.body_shape_hash,
        statement_sequence=member.statement_sequence,
        call_tokens=member.call_tokens,
    )


def _is_signature_only_low_info(
    _: list[_MemberContext],
    features: _ClassifierFeatures,
    structural_pairs: list[RelationPair],
) -> bool:
    if structural_pairs or features.boundary_specificity is not BoundarySpecificity.LOW:
        return False
    if features.statement_count_max <= TINY_FUNCTION_STATEMENT_COUNT:
        return not _tiny_function_has_strong_evidence(features)
    return len(features.corroborating_signals) < MIN_CORROBORATING_SIGNALS


def _symbols(members: list[_MemberContext]) -> set[str]:
    return {member.symbol for member in members if member.symbol}


def _containers(members: list[_MemberContext]) -> set[str]:
    return {member.container for member in members if member.container}


def _identical_statement_sequence(members: list[_MemberContext]) -> bool:
    sequences = {member.statement_sequence for member in members if member.statement_sequence}
    return len(sequences) == 1


def _all_members(
    members: list[_MemberContext],
    predicate: Callable[[_MemberContext], bool],
) -> bool:
    return bool(members) and all(predicate(member) for member in members)


def _shared_member_tokens(
    members: list[_MemberContext],
    tokens: Callable[[_MemberContext], tuple[str, ...]],
) -> bool:
    token_sets = [set(tokens(member)) for member in members]
    token_sets = [values for values in token_sets if values]
    return len(token_sets) == len(members) and bool(set.intersection(*token_sets))


def _classifier_features(
    members: list[_MemberContext],
    relation_pairs: list[RelationPair],
) -> _ClassifierFeatures:
    relation_kinds = frozenset(pair.relation_kind for pair in relation_pairs)
    same_module = _single_shared_value(members, lambda member: member.file)
    method_name_family = _shared_member_tokens(
        members,
        lambda member: cached_identifier_tokens(member.symbol),
    )
    shared_call_fingerprint = _shared_member_tokens(
        members,
        lambda member: member.call_tokens,
    )
    substantial_body = _has_substantial_shared_body(relation_pairs)
    max_name = _max_name_similarity(relation_pairs)
    statement_counts = [len(member.statement_sequence) for member in members]
    statement_min = min(statement_counts, default=0)
    statement_max = max(statement_counts, default=0)
    identical_sequence = _identical_statement_sequence(members)
    signals: list[str] = []
    if substantial_body:
        signals.append("normalized_body_hash_or_tree")
    if same_module:
        signals.append("same_module")
    if shared_call_fingerprint:
        signals.append("shared_call_fingerprint")
    if method_name_family or max_name >= HIGH_NAME_SIMILARITY:
        signals.append("method_name_family")
    if any(kind != RelationKind.NONE for kind in relation_kinds):
        signals.append("relation_kind")
    if identical_sequence:
        signals.append("identical_statement_sequence")
    if statement_min >= STABLE_STATEMENT_COUNT:
        signals.append("stable_statement_count")
    return _ClassifierFeatures(
        same_module=same_module,
        boundary_specificity=_boundary_specificity(members),
        method_name_family=method_name_family,
        shared_call_fingerprint=shared_call_fingerprint,
        substantial_shared_body=substantial_body,
        relation_kinds=relation_kinds,
        statement_count_max=statement_max,
        corroborating_signals=tuple(signals),
    )


def _corroborated_low_finding(
    features: _ClassifierFeatures,
    *,
    has_structural_pairs: bool,
) -> bool:
    if has_structural_pairs:
        return True
    if _tiny_function_has_strong_evidence(features):
        return True
    return len(features.corroborating_signals) >= MIN_CORROBORATING_SIGNALS


def _tiny_function_has_strong_evidence(features: _ClassifierFeatures) -> bool:
    if features.statement_count_max > TINY_FUNCTION_STATEMENT_COUNT:
        return False
    signals = set(features.corroborating_signals)
    return (
        "normalized_body_hash_or_tree" in signals
        or {
            "method_name_family",
            "shared_call_fingerprint",
        }
        <= signals
        or ("identical_statement_sequence" in signals and "shared_call_fingerprint" in signals)
    )


def _boundary_specificity(members: list[_MemberContext]) -> BoundarySpecificity:
    if any(member.type_source is not SignatureTypeSource.DECLARED_SYNTAX for member in members):
        return BoundarySpecificity.LOW
    member_values = [_member_boundary_specificity(member) for member in members]
    if all(value is BoundarySpecificity.HIGH for value in member_values):
        return BoundarySpecificity.HIGH
    if any(value is BoundarySpecificity.MEDIUM for value in member_values):
        return BoundarySpecificity.MEDIUM
    return BoundarySpecificity.LOW


def _member_boundary_specificity(member: _MemberContext) -> BoundarySpecificity:
    classes = (*member.parameter_classes, member.return_class)
    if member.return_class is SignatureTypeClass.UNKNOWN:
        return BoundarySpecificity.LOW
    if all(item is SignatureTypeClass.DOMAIN for item in classes):
        return BoundarySpecificity.HIGH
    if _has_low_specificity_parameter(member):
        return (
            BoundarySpecificity.MEDIUM
            if _domain_return_boundary(member)
            else BoundarySpecificity.LOW
        )
    if member.return_class is SignatureTypeClass.DOMAIN:
        return BoundarySpecificity.MEDIUM
    return BoundarySpecificity.LOW


def _has_low_specificity_parameter(member: _MemberContext) -> bool:
    return any(item in LOW_SPECIFICITY_PARAM_CLASSES for item in member.parameter_classes)


def _low_specificity_mapper(member: _MemberContext) -> bool:
    return (
        bool(member.parameter_classes)
        and all(item in LOW_SPECIFICITY_PARAM_CLASSES for item in member.parameter_classes)
        and member.return_class in LOW_SPECIFICITY_RETURN_CLASSES
    )


def _domain_return_boundary(member: _MemberContext) -> bool:
    if member.return_class is SignatureTypeClass.DOMAIN:
        return True
    if member.return_class is not SignatureTypeClass.COLLECTION:
        return False
    return collection_element_type_class(member.return_type) is SignatureTypeClass.DOMAIN


def _has_substantial_shared_body(relation_pairs: list[RelationPair]) -> bool:
    return any(
        pair.flags.body_hash_match or pair.tree.tree_similarity >= SUBSTANTIAL_TREE_SIMILARITY
        for pair in relation_pairs
    )


def _max_name_similarity(relation_pairs: list[RelationPair]) -> float:
    return max((float(pair.scores.name) for pair in relation_pairs), default=0.0)


def _shared_builder_lifecycle(members: list[_MemberContext]) -> bool:
    sequences = [member.statement_sequence for member in members if member.statement_sequence]
    if len(sequences) != len(members):
        return False
    prefix = _shared_edge_length(sequences, from_start=True)
    suffix = _shared_edge_length(sequences, from_start=False)
    return prefix >= MIN_SHARED_LIFECYCLE_EDGE or suffix >= MIN_SHARED_LIFECYCLE_EDGE


def _single_shared_value(
    members: list[_MemberContext],
    value: Callable[[_MemberContext], str],
) -> bool:
    values = {item for member in members if (item := value(member))}
    return len(values) == 1


def _return_shape(member: _MemberContext) -> str:
    return member.return_type.replace(" ", "").lower()


def _shared_edge_length(
    sequences: list[tuple[str, ...]],
    *,
    from_start: bool,
) -> int:
    length = min((len(sequence) for sequence in sequences), default=0)
    count = 0
    for index in range(length):
        items = [sequence[index if from_start else -index - 1] for sequence in sequences]
        if len(set(items)) != 1:
            break
        count += 1
    return count


__all__ = ["classify_contexts"]
