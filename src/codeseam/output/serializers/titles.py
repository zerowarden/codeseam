from __future__ import annotations

from typing import Literal

from codeseam.platform import Json, identifier_tokens, plural_noun, single_line

type EvidenceClass = Literal[
    "signature_shape",
    "body_tree_similarity",
    "statement_sequence_alignment",
    "control_context_similarity",
    "local_dataflow_similarity",
    "parameter_use_similarity",
    "name_similarity",
    "anti_unification_template",
    "argument_normalization_wrapper",
    "structural_duplicate",
    "policy_constant_duplicate",
]

REASON_PHRASES: dict[EvidenceClass, str] = {
    "signature_shape": "same signature shape",
    "body_tree_similarity": "similar body tree",
    "statement_sequence_alignment": "same statement sequence",
    "control_context_similarity": "same control flow",
    "local_dataflow_similarity": "similar data flow",
    "parameter_use_similarity": "similar parameter use",
    "name_similarity": "similar naming",
    "anti_unification_template": "common code skeleton",
    "argument_normalization_wrapper": "same downstream operation",
    "structural_duplicate": "structural duplicate",
    "policy_constant_duplicate": "duplicated policy constant",
}
REASON_PRIORITY: tuple[EvidenceClass, ...] = (
    "anti_unification_template",
    "body_tree_similarity",
    "local_dataflow_similarity",
    "control_context_similarity",
    "statement_sequence_alignment",
    "parameter_use_similarity",
    "structural_duplicate",
    "argument_normalization_wrapper",
    "policy_constant_duplicate",
    "name_similarity",
    "signature_shape",
)

STRUCTURAL_CLONE_EVIDENCE = {
    "anti_unification_template",
    "body_tree_similarity",
    "statement_sequence_alignment",
    "structural_duplicate",
}
SYMBOL_TITLE_STOPWORDS = {
    "a",
    "an",
    "as",
    "by",
    "for",
    "from",
    "get",
    "is",
    "set",
    "test",
    "to",
}
MAX_REASON_PHRASES = 3
SIGNATURE_SHAPE_PREFIX = "Shared signature shape "


def display_title(target: Json) -> str:
    evidence = _evidence_classes(target)
    symbols = _target_symbols(target)
    if "policy_constant_duplicate" in evidence:
        return _symbol_title("Duplicated policy constant", symbols)
    if "argument_normalization_wrapper" in evidence:
        return "Repeated argument normalization wrapper"
    if _is_clone_title_candidate(target, evidence):
        return _clone_title(symbols)
    return str(target.get("title", ""))


def display_reason(target: Json) -> str:
    evidence = _evidence_classes(target)
    phrases = [REASON_PHRASES[item] for item in REASON_PRIORITY if item in evidence]
    if phrases:
        return ", ".join(phrases[:MAX_REASON_PHRASES])
    reasons = target.get("reasons", [])
    if isinstance(reasons, list) and reasons:
        return str(reasons[0])
    return str(target.get("summary_reason") or "")


def display_reason_label(target: Json) -> str:
    return plural_noun(_reason_count(target), "Reason")


def display_sentence(text: object) -> str:
    value = str(text or "").strip()
    return f"{value[:1].upper()}{value[1:]}" if value else ""


def display_action_title(action: object) -> str:
    value = str(action or "").strip()
    if not value:
        return "Observe"
    words = " ".join(value.split("_"))
    return display_sentence(words)


def display_shape(title: object) -> str:
    text = str(title or "")
    if text.startswith(SIGNATURE_SHAPE_PREFIX):
        return text.removeprefix(SIGNATURE_SHAPE_PREFIX)
    return ""


def _evidence_classes(target: Json) -> set[str]:
    values = target.get("evidence_classes", [])
    return {item for item in values if isinstance(item, str)} if isinstance(values, list) else set()


def _target_symbols(target: Json) -> list[str]:
    locations = target.get("locations", [])
    if not isinstance(locations, list):
        return []
    return sorted(
        {
            str(location.get("symbol", ""))
            for location in locations
            if isinstance(location, dict) and location.get("symbol")
        }
    )


def _is_clone_title_candidate(target: Json, evidence: set[str]) -> bool:
    return str(target.get("primary_action")) == "consolidate_clone" or bool(
        evidence & STRUCTURAL_CLONE_EVIDENCE
    )


def _reason_count(target: Json) -> int:
    reasons = target.get("reasons")
    if isinstance(reasons, list):
        return max(1, sum(1 for reason in reasons if single_line(reason)))
    reason = single_line(target.get("reason"))
    if reason:
        return max(1, len([part for part in reason.split(",") if part.strip()]))
    return 1


def _clone_title(symbols: list[str]) -> str:
    if len(symbols) == 1:
        return f"Duplicate helper {symbols[0]}"
    if shared := _shared_symbol_tokens(symbols):
        return f"Duplicate {' '.join(shared)} helpers"
    return "Duplicate helpers with similar structure"


def _shared_symbol_tokens(symbols: list[str]) -> tuple[str, ...]:
    token_sets = [set(_title_tokens(symbol)) for symbol in symbols]
    if not token_sets:
        return ()
    shared = set.intersection(*token_sets)
    return tuple(token for token in _title_tokens(symbols[0]) if token in shared)[:2]


def _title_tokens(symbol: str) -> tuple[str, ...]:
    return tuple(
        token
        for token in identifier_tokens(symbol)
        if token not in SYMBOL_TITLE_STOPWORDS and not token.isdigit()
    )


def _symbol_title(prefix: str, symbols: list[str]) -> str:
    return f"{prefix} {symbols[0]}" if len(symbols) == 1 else prefix


__all__ = [
    "display_action_title",
    "display_reason",
    "display_reason_label",
    "display_sentence",
    "display_shape",
    "display_title",
]
