from __future__ import annotations

from collections.abc import Callable

from codeseam.analysis import SignatureAnalysis, member_features, structural_shingles


def _shingles(
    signature_analysis: Callable[..., SignatureAnalysis],
    symbol: str,
    **overrides: object,
) -> frozenset[str]:
    return structural_shingles(member_features(signature_analysis(symbol, **overrides)))


def test_structural_shingles_are_deterministic_and_categorized(
    signature_analysis: Callable[..., SignatureAnalysis],
) -> None:
    shingles = _shingles(
        signature_analysis,
        "format_payload",
        statements=("ASSIGN:CALL:json.dumps", "RETURN:ARG0"),
        calls=("json.dumps(args=ARG0;kwargs=)",),
        arg_reads=((0, ("ARG0",)), (1, ("ARG1",))),
        controls=("TRY",),
    )

    assert shingles == _shingles(
        signature_analysis,
        "format_payload",
        statements=("ASSIGN:CALL:json.dumps", "RETURN:ARG0"),
        calls=("json.dumps(args=ARG0;kwargs=)",),
        arg_reads=((0, ("ARG0",)), (1, ("ARG1",))),
        controls=("TRY",),
    )
    assert {
        "STMT:ASSIGN:CALL",
        "STMT:RETURN:ARG",
        "BIGRAM:ASSIGN:CALL->RETURN:ARG",
        "CALL:json.dumps",
        "FLOW:ARG->CALL",
        "FLOW:ARG->RETURN",
        "CTRL_CALL:TRY|CALL:json.dumps",
    } <= shingles
    assert {item.split(":", 1)[0] for item in shingles} == {
        "BIGRAM",
        "CALL",
        "CTRL_CALL",
        "FLOW",
        "STMT",
    }


def test_structural_shingles_normalize_statement_and_argument_details(
    signature_analysis: Callable[..., SignatureAnalysis],
) -> None:
    left = _shingles(
        signature_analysis,
        "left",
        statements=("ASSIGN:CALL:path.write_text", "RETURN:ARG0"),
        calls=("path.write_text(args=ARG0;kwargs=)",),
        arg_reads=((0, ("ARG0",)),),
    )
    right = _shingles(
        signature_analysis,
        "right",
        statements=("ASSIGN:CALL:path.write_text", "RETURN:ARG7"),
        calls=("path.write_text(args=ARG7;kwargs=)",),
        arg_reads=((0, ("ARG7",)),),
    )

    assert {
        "STMT:ASSIGN:CALL",
        "STMT:RETURN:ARG",
        "FLOW:ARG->CALL",
    } <= left & right
