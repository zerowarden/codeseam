from __future__ import annotations

from codeseam.analysis import AssignKind, ControlKind, StatementKind

CALLABLE_TYPES = frozenset(
    {
        "function_declaration",
        "function_signature",
        "method_definition",
        "method_signature",
        "abstract_method_signature",
        "function_expression",
        "arrow_function",
    }
)
BODY_CALLABLE_TYPES = frozenset(
    {
        "function_declaration",
        "method_definition",
        "function_expression",
        "arrow_function",
    }
)
# `class` is a class expression (`const A = class {}`, `export default class {}`).
CLASS_TYPES = frozenset({"class_declaration", "abstract_class_declaration", "class"})
NESTED_SCOPE_TYPES = BODY_CALLABLE_TYPES | CLASS_TYPES
# Python counterparts are in `python/signature_features.py`; keep the two in step.
BRANCH_TYPES = frozenset({"if_statement", "ternary_expression", "switch_case", "catch_clause"})
LOOP_TYPES = frozenset({"for_statement", "for_in_statement", "while_statement", "do_statement"})
NESTING_TYPES = LOOP_TYPES | frozenset(
    {"if_statement", "switch_statement", "try_statement", "with_statement"}
)
CALL_TYPES = frozenset({"call_expression", "new_expression"})
DECLARATION_TYPES = frozenset({"lexical_declaration", "variable_declaration"})
ASSIGN_EXPRESSION_KINDS = {
    "assignment_expression": AssignKind.BIND,
    "augmented_assignment_expression": AssignKind.UPDATE,
    "update_expression": AssignKind.UPDATE,
}
STATEMENT_KINDS = {
    "if_statement": StatementKind.IF,
    "switch_statement": StatementKind.SWITCH,
    **dict.fromkeys(LOOP_TYPES, StatementKind.LOOP),
    "try_statement": StatementKind.TRY,
    "throw_statement": StatementKind.RAISE,
    "function_declaration": StatementKind.DEFINE,
    "generator_function_declaration": StatementKind.DEFINE,
    "class_declaration": StatementKind.DEFINE,
    "break_statement": StatementKind.BREAK,
    "continue_statement": StatementKind.CONTINUE,
    "empty_statement": StatementKind.PASS,
    "expression_statement": StatementKind.EXPR,
}
CONTROL_KINDS = {
    "if_statement": ControlKind.BRANCH,
    "switch_statement": ControlKind.BRANCH,
    **dict.fromkeys(LOOP_TYPES, ControlKind.LOOP),
    "try_statement": ControlKind.TRY,
    "catch_clause": ControlKind.CATCH,
    "with_statement": ControlKind.WITH,
    "await_expression": ControlKind.AWAIT,
}
JSX_TYPES = frozenset(
    {"jsx_element", "jsx_self_closing_element", "jsx_fragment", "jsx_opening_element"}
)
CONTROL_BLOCK_PARENTS = frozenset(
    {
        "if_statement",
        "else_clause",
        "catch_clause",
        "finally_clause",
    }
)
CONTROL_CONTAINER_TYPES = CONTROL_BLOCK_PARENTS | frozenset(
    {
        "for_statement",
        "for_in_statement",
        "while_statement",
        "do_statement",
        "switch_statement",
        "try_statement",
    }
)
IGNORED_STATEMENT_TYPES = frozenset({"comment"})

TSX_SUFFIXES = frozenset({".tsx"})
TYPESCRIPT_SUFFIXES = frozenset({".ts", ".mts", ".cts"})

__all__ = [
    "ASSIGN_EXPRESSION_KINDS",
    "BODY_CALLABLE_TYPES",
    "CALL_TYPES",
    "CONTROL_KINDS",
    "DECLARATION_TYPES",
    "NESTING_TYPES",
    "STATEMENT_KINDS",
    "BRANCH_TYPES",
    "CALLABLE_TYPES",
    "CLASS_TYPES",
    "CONTROL_BLOCK_PARENTS",
    "CONTROL_CONTAINER_TYPES",
    "IGNORED_STATEMENT_TYPES",
    "JSX_TYPES",
    "LOOP_TYPES",
    "NESTED_SCOPE_TYPES",
    "TSX_SUFFIXES",
    "TYPESCRIPT_SUFFIXES",
]
