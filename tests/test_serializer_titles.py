from __future__ import annotations

from codeseam.output.serializers.titles import (
    display_action_title,
    display_reason,
    display_reason_label,
    display_sentence,
    display_shape,
    display_title,
)
from codeseam.platform import Json


def test_display_title_uses_literal_duplicate_symbol() -> None:
    target = _target(
        symbols=["fake_write_bot_match_review"],
        evidence_classes=["anti_unification_template", "body_tree_similarity"],
    )

    assert display_title(target) == "Duplicate helper fake_write_bot_match_review"


def test_display_title_uses_shared_symbol_tokens() -> None:
    target = _target(
        symbols=["_mulligan_score", "_selection_score"],
        evidence_classes=["anti_unification_template", "body_tree_similarity"],
    )

    assert display_title(target) == "Duplicate score helpers"


def test_display_title_falls_back_to_structural_clone_title() -> None:
    target = _target(
        symbols=["_summarize_action", "_render_event"],
        evidence_classes=["body_tree_similarity"],
    )

    assert display_title(target) == "Duplicate helpers with similar structure"


def test_display_title_uses_evidence_specific_titles() -> None:
    assert (
        display_title(_target(evidence_classes=["argument_normalization_wrapper"]))
        == "Repeated argument normalization wrapper"
    )
    assert (
        display_title(
            _target(
                symbols=["MAX_RETRIES"],
                evidence_classes=["policy_constant_duplicate"],
                primary_action="introduce_abstraction",
            )
        )
        == "Duplicated policy constant MAX_RETRIES"
    )


def test_display_reason_and_shape_are_compact() -> None:
    target = _target(
        title="Shared signature shape fn(str)->bool",
        evidence_classes=[
            "anti_unification_template",
            "body_tree_similarity",
            "local_dataflow_similarity",
            "signature_shape",
        ],
    )

    assert display_shape(target["title"]) == "fn(str)->bool"
    assert display_reason(target) == "common code skeleton, similar body tree, similar data flow"


def test_display_reason_label_uses_plural_for_multiple_reasons() -> None:
    assert display_reason_label({"reason": "common code skeleton"}) == "Reason"
    assert display_reason_label({"reason": "common code skeleton, similar body tree"}) == "Reasons"
    assert display_reason_label({"reasons": ["common code skeleton", "similar body tree"]}) == (
        "Reasons"
    )


def test_display_sentence_and_action_title_are_human_readable() -> None:
    assert display_sentence("common code skeleton") == "Common code skeleton"
    assert display_action_title("consolidate_clone") == "Consolidate clone"


def _target(
    *,
    symbols: list[str] | None = None,
    evidence_classes: list[str] | None = None,
    primary_action: str = "consolidate_clone",
    title: str = "Shared signature shape fn(str)->str",
) -> Json:
    return {
        "title": title,
        "primary_action": primary_action,
        "evidence_classes": evidence_classes or [],
        "locations": [
            {"symbol": symbol, "file": f"src/{index}.py", "start_line": index}
            for index, symbol in enumerate(symbols or [], start=1)
        ],
    }
