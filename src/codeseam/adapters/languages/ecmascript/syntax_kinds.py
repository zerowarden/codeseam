from __future__ import annotations

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
NESTED_SCOPE_TYPES = BODY_CALLABLE_TYPES | frozenset({"class_declaration"})
BRANCH_TYPES = frozenset({"if_statement", "switch_statement", "case_statement", "catch_clause"})
LOOP_TYPES = frozenset({"for_statement", "for_in_statement", "while_statement", "do_statement"})
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
    "BODY_CALLABLE_TYPES",
    "BRANCH_TYPES",
    "CALLABLE_TYPES",
    "CONTROL_BLOCK_PARENTS",
    "CONTROL_CONTAINER_TYPES",
    "IGNORED_STATEMENT_TYPES",
    "JSX_TYPES",
    "LOOP_TYPES",
    "NESTED_SCOPE_TYPES",
    "TSX_SUFFIXES",
    "TYPESCRIPT_SUFFIXES",
]
