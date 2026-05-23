from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from codeseam.analysis import SignatureAnalysis, member_features, structural_shingles


@dataclass(frozen=True, slots=True)
class ShingleCase:
    symbol: str
    statements: tuple[str, ...]
    calls: tuple[str, ...]
    arg_reads: tuple[tuple[int, tuple[str, ...]], ...]
    controls: tuple[str, ...] = ()


def _shingles(
    signature_analysis: Callable[..., SignatureAnalysis],
    case: ShingleCase,
) -> frozenset[str]:
    return structural_shingles(
        member_features(
            signature_analysis(
                case.symbol,
                statements=case.statements,
                calls=case.calls,
                arg_reads=case.arg_reads,
                controls=case.controls,
            )
        )
    )


def test_structural_shingles_are_deterministic_and_categorized(
    signature_analysis: Callable[..., SignatureAnalysis],
) -> None:
    case = ShingleCase(
        symbol="format_payload",
        statements=("ASSIGN:CALL:json.dumps", "RETURN:ARG0"),
        calls=("json.dumps(args=ARG0;kwargs=)",),
        arg_reads=((0, ("ARG0",)), (1, ("ARG1",))),
        controls=("TRY",),
    )
    shingles = _shingles(signature_analysis, case)

    assert shingles == _shingles(signature_analysis, case)
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
        ShingleCase(
            symbol="left",
            statements=("ASSIGN:CALL:path.write_text", "RETURN:ARG0"),
            calls=("path.write_text(args=ARG0;kwargs=)",),
            arg_reads=((0, ("ARG0",)),),
        ),
    )
    right = _shingles(
        signature_analysis,
        ShingleCase(
            symbol="right",
            statements=("ASSIGN:CALL:path.write_text", "RETURN:ARG7"),
            calls=("path.write_text(args=ARG7;kwargs=)",),
            arg_reads=((0, ("ARG7",)),),
        ),
    )

    assert {
        "STMT:ASSIGN:CALL",
        "STMT:RETURN:ARG",
        "FLOW:ARG->CALL",
    } <= left & right
