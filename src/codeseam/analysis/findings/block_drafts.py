"""Drafts for duplicated blocks: inside one function, or shared between functions."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from codeseam.analysis.clusters import Cluster
from codeseam.analysis.findings.definitions import FindingTargetType
from codeseam.analysis.findings.locations import line_span
from codeseam.analysis.findings.metrics import semantic_role_member_metrics
from codeseam.analysis.findings.models import (
    EvidenceItem,
    FindingDraft,
    FindingLocation,
    FindingMetrics,
)
from codeseam.analysis.relations import (
    AbstractionKind,
    ActionKind,
    ActionStatus,
    EvidenceKind,
)
from codeseam.analysis.relations.blocks import SharedBlock, shared_blocks
from codeseam.analysis.relations.models import (
    RefactorAction,
    member_ref,
)
from codeseam.analysis.relations.summary import summarize_actions
from codeseam.analysis.semantic_roles import role_counts
from codeseam.analysis.signatures import (
    ExtractionConfidence,
    IntraFunctionDuplicateBlock,
    NormalizationLevel,
    SignatureAnalysis,
    SignatureCore,
)


def build_intra_function_duplicate_drafts(
    signatures: Sequence[SignatureAnalysis],
) -> list[FindingDraft]:
    """Build findings for repeated blocks inside a single function.

    Cross-function clustering only sees whole functions. This draft path turns
    adapter-collected local block evidence into the same language-neutral
    assessment flow used by relation findings.
    """

    drafts: list[FindingDraft] = []
    for signature in signatures:
        core = signature.core
        for index, block in enumerate(core.intra_function_duplicate_blocks, 1):
            drafts.append(_intra_function_duplicate_draft(core, block, index))
    return drafts


def build_shared_block_drafts(
    signatures: Sequence[SignatureAnalysis], clusters: Sequence[Cluster]
) -> list[FindingDraft]:
    """Findings for statement blocks shared by otherwise different functions.

    Pairs already found as whole-function clones are skipped, so a clone is
    never reported twice. A pair that is only related as a whole (it differs
    too much to consolidate) can still share a block worth extracting.
    """

    related = {
        frozenset(
            (
                (pair.left.file, pair.left.start_line, pair.left.symbol),
                (pair.right.file, pair.right.start_line, pair.right.symbol),
            )
        )
        for cluster in clusters
        if cluster.enrichment is not None
        for pair in cluster.enrichment.structural_duplicate_pairs
    }
    cores = [signature.core for signature in signatures]
    return [_shared_block_draft(block) for block in shared_blocks(cores, related=related)]


def _shared_block_draft(block: SharedBlock) -> FindingDraft:
    members = block.members
    locations = [
        FindingLocation(
            file=item.member.file,
            start_line=item.start_line,
            end_line=item.end_line,
            source="shared_block",
            kind="duplicate_block",
            symbol=item.member.symbol,
            message="Statement block shared with other functions.",
            container=item.member.container or "",
        )
        for item in block.occurrences
    ]
    line_counts = [item.line_count for item in block.occurrences]
    action = RefactorAction(
        kind=ActionKind.EXTRACT_SMALL_HELPER,
        status=ActionStatus.RECOMMENDED,
        confidence=0.85,
        applies_to=tuple(member_ref(core) for core in members),
        preconditions=("shared_block",),
        reason_codes=("SHARED_BLOCK",),
    )
    names = " / ".join(dict.fromkeys(core.symbol for core in members))
    return FindingDraft(
        target_type=FindingTargetType.SIGNATURE_SHAPE,
        title=f"Shared block in {names}",
        severity="medium",
        confidence=0.85,
        files=list(dict.fromkeys(core.file for core in members)),
        locations=locations,
        metrics=FindingMetrics(
            member_count=len(members),
            canonical_shape=f"shared_block({block.statement_count} statements)",
            cluster_scope="same_language",
            normalization_level=NormalizationLevel.CONTROL,
            language_count=1,
            adapter_count=1,
            min_extraction_confidence=ExtractionConfidence.HIGH,
            duplicate_block_count=1,
            duplicate_block_line_count=sum(line_counts),
            max_body_line_count=max(line_counts),
            min_body_line_count=min(line_counts),
            lead_stable_statement_count=block.statement_count,
            min_stable_statement_count=min(item.length for item in block.occurrences),
            lead_tree_similarity=1.0,
            lead_relatedness_score=0.85,
            lead_refactorability_score=0.8,
            lead_confidence_score=0.85,
            # Statement keys abstract names and literal values, so the copies
            # may differ in data a helper would have to take as parameters.
            lead_risk_score=0.1,
            semantic_role_counts=role_counts(
                role for core in members for role in core.semantic_roles
            ),
            semantic_role_reasons=tuple(
                dict.fromkeys(reason for core in members for reason in core.semantic_role_reasons)
            ),
            **cast(
                Any,
                semantic_role_member_metrics(
                    members, member_count=len(members), sync_async_surface=False
                ),
            ),
        ),
        evidence=[EvidenceItem(EvidenceKind.SHARED_BLOCK, id=block.fingerprint)],
        reasons=[
            f"A block of {block.statement_count} statements appears in {len(members)} functions.",
            "The functions differ elsewhere, so whole-function comparison does not pair them.",
        ],
        risk="low",
        direction=(
            "Extract the shared block into a helper that the functions call, passing in "
            "any names or values that differ between the copies."
        ),
        overlaps={"signatures": tuple(core.signature_id for core in members)},
        member_count=len(members),
        has_signature_overlap=False,
        line_span=line_span(locations),
        non_claims=[
            "Only the block is shared; the rest of each function is different.",
            "Copies may differ in names or literal values that a helper must take as parameters.",
        ],
        abstraction_kind=AbstractionKind.EXTRACT_HELPER,
        evidence_kinds=[EvidenceKind.SHARED_BLOCK],
        refactor_action_candidates=[action],
        refactor_action_summary=summarize_actions([action]),
    )


def _intra_function_duplicate_draft(
    core: SignatureCore,
    block: IntraFunctionDuplicateBlock,
    index: int,
) -> FindingDraft:
    locations = _intra_function_duplicate_locations(core, block)
    action = RefactorAction(
        kind=ActionKind.EXTRACT_SMALL_HELPER,
        status=ActionStatus.RECOMMENDED,
        confidence=0.9,
        applies_to=(member_ref(core),),
        preconditions=("intra_function_duplicate_block",),
        reason_codes=("INTRA_FUNCTION_DUPLICATE_BLOCK",),
    )
    return FindingDraft(
        target_type=FindingTargetType.SIGNATURE_SHAPE,
        title=f"Repeated local block in {core.symbol}",
        severity="medium",
        confidence=0.9,
        files=[core.file],
        locations=locations,
        metrics=FindingMetrics(
            member_count=1,
            canonical_shape=core.canonical_shape,
            cluster_scope="same_language",
            normalization_level=NormalizationLevel.CONTROL,
            language_count=1,
            adapter_count=1,
            min_extraction_confidence=ExtractionConfidence.HIGH,
            duplicate_block_count=1,
            duplicate_block_line_count=sum(
                occurrence.end_line - occurrence.start_line + 1 for occurrence in block.occurrences
            ),
            max_body_line_count=block.line_count,
            min_body_line_count=block.line_count,
            lead_stable_statement_count=block.statement_count,
            min_stable_statement_count=block.statement_count,
            lead_tree_similarity=1.0,
            lead_relatedness_score=0.9,
            lead_refactorability_score=0.85,
            lead_confidence_score=0.9,
            lead_risk_score=0.04,
            semantic_role_counts=role_counts(core.semantic_roles),
            semantic_role_reasons=tuple(core.semantic_role_reasons),
            **cast(
                Any,
                semantic_role_member_metrics(
                    (core,),
                    member_count=1,
                    sync_async_surface=False,
                ),
            ),
        ),
        evidence=[
            EvidenceItem(
                EvidenceKind.INTRA_FUNCTION_DUPLICATE,
                id=f"{core.signature_id}:{index}:{block.fingerprint}",
            )
        ],
        reasons=[
            "The same normalized block appears more than once inside this function.",
            (
                "The duplicate is local, so extraction can be considered without changing "
                "module boundaries."
            ),
        ],
        risk="low",
        direction=(
            "Extract the repeated local block into a small helper only if it preserves "
            "the guard or error semantics."
        ),
        overlaps={"signatures": (core.signature_id,)},
        member_count=1,
        has_signature_overlap=False,
        line_span=line_span(locations),
        non_claims=[
            "The repeated block is local to one function.",
            "Extraction still needs a semantic check before editing guard or error handling.",
        ],
        abstraction_kind=AbstractionKind.EXTRACT_HELPER,
        evidence_kinds=[EvidenceKind.INTRA_FUNCTION_DUPLICATE],
        refactor_action_candidates=[action],
        refactor_action_summary=summarize_actions([action]),
    )


def _intra_function_duplicate_locations(
    core: SignatureCore,
    block: IntraFunctionDuplicateBlock,
) -> list[FindingLocation]:
    return [
        FindingLocation(
            file=core.file,
            start_line=occurrence.start_line,
            end_line=occurrence.end_line,
            source="intra_function_duplicate",
            kind=block.kind,
            symbol=core.symbol,
            message="Repeated local block within this function.",
            container=core.container or "",
        )
        for occurrence in block.occurrences
    ]


__all__ = [
    "build_intra_function_duplicate_drafts",
    "build_shared_block_drafts",
]
