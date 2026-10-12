"""The language-neutral vocabulary every adapter emits.

Thresholds, buckets and heuristics read statement tokens, control kinds and
default-value roles without knowing the language, so each adapter maps its
own syntax onto these names. `tests/test_adapter_parity.py` checks that
equivalent Python and TypeScript functions produce equal features.
"""

from __future__ import annotations

from enum import StrEnum


class StatementKind(StrEnum):
    ASSIGN = "ASSIGN"  # always ASSIGN:BIND or ASSIGN:UPDATE
    CALL = "CALL"  # CALL:<call token>; a call, or an awaited call, as a statement
    RETURN = "RETURN"  # RETURN:<sorted parameter reads>
    WITH = "WITH"  # WITH:<context call tokens>
    IF = "IF"
    SWITCH = "SWITCH"
    LOOP = "LOOP"
    TRY = "TRY"
    RAISE = "RAISE"
    DEFINE = "DEFINE"  # nested function or class
    BREAK = "BREAK"
    CONTINUE = "CONTINUE"
    PASS = "PASS"
    ASSERT = "ASSERT"
    DELETE = "DELETE"
    IMPORT = "IMPORT"
    DECLARE = "DECLARE"  # global, nonlocal, or an annotation without a value
    EXPR = "EXPR"  # any other expression statement
    OTHER = "OTHER"


class AssignKind(StrEnum):
    BIND = "BIND"  # x = v, const x = v
    UPDATE = "UPDATE"  # x += v, x++


class ControlKind(StrEnum):
    BRANCH = "BRANCH"
    LOOP = "LOOP"
    TRY = "TRY"
    CATCH = "CATCH"
    WITH = "WITH"
    AWAIT = "AWAIT"


DETAILED_STATEMENTS = frozenset(
    {StatementKind.ASSIGN, StatementKind.CALL, StatementKind.RETURN, StatementKind.WITH}
)
# Role of a parameter default that is not a literal.
DEFAULT_EXPRESSION = "EXPR"


def statement_token(kind: StatementKind, detail: str = "") -> str:
    return f"{kind.value}:{detail}" if kind in DETAILED_STATEMENTS else kind.value


def assign_token(kind: AssignKind) -> str:
    return statement_token(StatementKind.ASSIGN, kind.value)


__all__ = [
    "DEFAULT_EXPRESSION",
    "AssignKind",
    "ControlKind",
    "StatementKind",
    "assign_token",
    "statement_token",
]
