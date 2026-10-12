"""How much of the repository an analysis actually covered.

A report with no findings means "no repetition worth attention" only when the
analysis was complete. This summary says which files parsed, which evidence
methods ran, and which limits cut the comparison short, and it classifies the
run as complete, partial or insufficient.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from codeseam.platform import Json

# Diagnostic prefixes. Adapters and extraction write them; this module reads them.
SOURCE_CHANGED = "source_changed"
EXTRACTION_FAILED = "extraction_failed"
PYTHON_PARSE_ERROR = "python_parse_error"
TREE_SITTER_PARSE_ERROR = "tree_sitter_parse_error"
NO_FUNCTIONS_RECOVERED = "no functions recovered"
# A run is insufficient when at least this share of its source files failed.
INSUFFICIENT_FAILED_SHARE = 0.5


class Coverage(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    INSUFFICIENT = "insufficient"


class FileOutcome(StrEnum):
    ANALYSED = "analysed"
    PARTIAL = "partial"  # parsed with syntax errors; some functions recovered
    FAILED = "failed"  # nothing extracted
    CHANGED = "changed"  # edited after the scan; analysed next run


class MethodStatus(StrEnum):
    RAN = "ran"
    SKIPPED = "skipped"  # nothing to run it on
    UNAVAILABLE = "unavailable"  # wanted, but could not run


def file_outcome(diagnostics: Iterable[str]) -> FileOutcome:
    found = tuple(diagnostics)
    if any(item.startswith(SOURCE_CHANGED) for item in found):
        return FileOutcome.CHANGED
    if any(
        item.startswith((EXTRACTION_FAILED, PYTHON_PARSE_ERROR)) or NO_FUNCTIONS_RECOVERED in item
        for item in found
    ):
        return FileOutcome.FAILED
    if any(item.startswith(TREE_SITTER_PARSE_ERROR) for item in found):
        return FileOutcome.PARTIAL
    return FileOutcome.ANALYSED


@dataclass(frozen=True, slots=True)
class EvidenceMethod:
    name: str
    status: MethodStatus
    note: str = ""


@dataclass(frozen=True, slots=True)
class CompletenessInputs:
    """What the pipeline knows after a run; all counts are plain numbers."""

    source_files: int  # selected files in a supported language
    diagnostics: Mapping[str, tuple[str, ...]]
    unsupported_source_files: Mapping[str, int]  # language -> count, no adapter
    function_count: int
    comparison_stats: Mapping[str, int]
    # Relation pairs by how their tree similarity was found: measured or estimated.
    trees_measured: int = 0
    trees_estimated: int = 0
    policy_constant_languages: frozenset[str] = frozenset()
    semantic_requested: bool = False
    semantic_answered: int = 0
    semantic_caveats: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CompletenessSummary:
    coverage: Coverage
    reasons: tuple[str, ...]
    notes: tuple[str, ...]
    files: dict[str, int]
    unsupported_source_files: dict[str, int]
    function_count: int
    comparisons: dict[str, int]
    methods: tuple[EvidenceMethod, ...] = field(default=())

    def payload(self) -> Json:
        return {
            "coverage": self.coverage.value,
            "reasons": list(self.reasons),
            "notes": list(self.notes),
            "files": dict(self.files),
            "unsupported_source_files": dict(self.unsupported_source_files),
            "function_count": self.function_count,
            "comparisons": dict(self.comparisons),
            "evidence_methods": [
                {"name": method.name, "status": method.status.value, "note": method.note}
                for method in self.methods
            ],
        }



def completeness_summary(inputs: CompletenessInputs) -> CompletenessSummary:
    outcomes = Counter(file_outcome(items) for items in inputs.diagnostics.values())
    troubled = sum(outcomes.values())
    files = {
        FileOutcome.ANALYSED.value: max(0, inputs.source_files - troubled),
        **{
            outcome.value: outcomes[outcome]
            for outcome in FileOutcome
            if outcome.value != "analysed"
        },
    }
    stats = inputs.comparison_stats
    comparisons = {
        "pairs_compared": stats.get("candidate_pair_count", 0),
        "pairs_cut_by_limit": stats.get("candidate_pairs_truncated_count", 0),
        "bucket_members_cut_by_limit": stats.get("candidate_bucket_members_truncated_count", 0),
        "related_pairs_tree_measured": inputs.trees_measured,
        "related_pairs_tree_estimated": inputs.trees_estimated,
    }
    reasons = _reasons(inputs, files, comparisons)
    return CompletenessSummary(
        coverage=_coverage(inputs, files, reasons),
        reasons=tuple(reasons),
        notes=tuple(_notes(comparisons)),
        files=files,
        unsupported_source_files=dict(sorted(inputs.unsupported_source_files.items())),
        function_count=inputs.function_count,
        comparisons=comparisons,
        methods=_methods(inputs, comparisons),
    )


def _reasons(
    inputs: CompletenessInputs, files: dict[str, int], comparisons: dict[str, int]
) -> list[str]:
    reasons: list[str] = []
    if not inputs.source_files:
        reasons.append("no source files in a supported language were selected")
    elif not inputs.function_count:
        reasons.append("no functions were extracted")
    for outcome, text in (
        (FileOutcome.FAILED, "could not be parsed"),
        (FileOutcome.PARTIAL, "had syntax errors; some functions were skipped"),
        (FileOutcome.CHANGED, "changed during the run and were not analysed"),
    ):
        if count := files[outcome.value]:
            reasons.append(f"{count} file(s) {text}")
    if unsupported := sum(inputs.unsupported_source_files.values()):
        languages = ", ".join(sorted(inputs.unsupported_source_files))
        reasons.append(f"{unsupported} source file(s) in unsupported languages ({languages})")
    if inputs.semantic_requested and not inputs.semantic_answered:
        caveats = ", ".join(inputs.semantic_caveats) or "no provider"
        reasons.append(f"semantic provider was requested but did not run ({caveats})")
    return reasons


def _notes(comparisons: dict[str, int]) -> list[str]:
    """Limits that bound the work but do not leave code unanalysed.

    Candidate pairs are cut lowest-estimated-similarity first, so the cut pairs
    are the least likely clones. They are reported, not counted against coverage.
    """

    notes = []
    if pairs := comparisons["pairs_cut_by_limit"]:
        notes.append(f"{pairs} low-ranked candidate pair(s) were not compared")
    if members := comparisons["bucket_members_cut_by_limit"]:
        notes.append(
            f"{members} bucket place(s) past the size limit were left out; those functions "
            "can still meet in other buckets and through the content index"
        )
    return notes


def _coverage(inputs: CompletenessInputs, files: dict[str, int], reasons: list[str]) -> Coverage:
    lost = files[FileOutcome.FAILED.value] + files[FileOutcome.CHANGED.value]
    unsupported = sum(inputs.unsupported_source_files.values())
    if (
        not inputs.source_files
        or not inputs.function_count
        or lost >= INSUFFICIENT_FAILED_SHARE * inputs.source_files
        or unsupported > inputs.source_files
    ):
        return Coverage.INSUFFICIENT
    return Coverage.PARTIAL if reasons else Coverage.COMPLETE


def _methods(inputs: CompletenessInputs, comparisons: dict[str, int]) -> tuple[EvidenceMethod, ...]:
    def status(ran: bool) -> MethodStatus:
        return MethodStatus.RAN if ran else MethodStatus.SKIPPED

    functions = inputs.function_count > 0
    estimated = comparisons["related_pairs_tree_estimated"]
    semantic = (
        MethodStatus.RAN
        if inputs.semantic_answered
        else MethodStatus.UNAVAILABLE
        if inputs.semantic_requested
        else MethodStatus.SKIPPED
    )
    return (
        EvidenceMethod("signature_shape_buckets", status(functions)),
        EvidenceMethod("content_index", status(functions)),
        EvidenceMethod("shared_blocks", status(functions)),
        EvidenceMethod(
            "tree_edit_distance",
            status(comparisons["related_pairs_tree_measured"] > 0),
            f"{estimated} pair(s) used the statement-key estimate" if estimated else "",
        ),
        EvidenceMethod(
            "policy_constants",
            status(bool(inputs.policy_constant_languages)),
            ", ".join(sorted(inputs.policy_constant_languages)),
        ),
        EvidenceMethod(
            "semantic_provider",
            semantic,
            "" if inputs.semantic_requested else "semantics.mode is off",
        ),
    )


__all__ = [
    "EXTRACTION_FAILED",
    "NO_FUNCTIONS_RECOVERED",
    "PYTHON_PARSE_ERROR",
    "SOURCE_CHANGED",
    "TREE_SITTER_PARSE_ERROR",
    "CompletenessInputs",
    "CompletenessSummary",
    "Coverage",
    "EvidenceMethod",
    "FileOutcome",
    "MethodStatus",
    "completeness_summary",
    "file_outcome",
]
