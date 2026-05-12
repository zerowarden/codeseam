from __future__ import annotations

import ast
import re
from typing import cast

from codeseam.analysis import (
    FunctionSemanticRole,
    FunctionSemanticRoles,
    PathSemanticRoleOptions,
    path_semantic_roles,
)

DUNDER_RE = re.compile(r"^__[A-Za-z_][A-Za-z0-9_]*__$")

OPERATOR_DUNDERS = frozenset(
    {
        "__add__",
        "__radd__",
        "__sub__",
        "__rsub__",
        "__mul__",
        "__rmul__",
        "__matmul__",
        "__rmatmul__",
        "__truediv__",
        "__rtruediv__",
        "__floordiv__",
        "__rfloordiv__",
        "__mod__",
        "__rmod__",
        "__pow__",
        "__rpow__",
        "__lshift__",
        "__rlshift__",
        "__rshift__",
        "__rrshift__",
        "__and__",
        "__rand__",
        "__xor__",
        "__rxor__",
        "__or__",
        "__ror__",
        "__iadd__",
        "__isub__",
        "__imul__",
        "__imatmul__",
        "__itruediv__",
        "__ifloordiv__",
        "__imod__",
        "__ipow__",
        "__ilshift__",
        "__irshift__",
        "__iand__",
        "__ixor__",
        "__ior__",
        "__neg__",
        "__pos__",
        "__abs__",
        "__invert__",
    }
)
DESCRIPTOR_DUNDERS = frozenset({"__get__", "__set__", "__delete__", "__set_name__"})
ATTRIBUTE_ACCESS_DUNDERS = frozenset(
    {"__getattr__", "__getattribute__", "__setattr__", "__delattr__", "__dir__"}
)
COMPARISON_DUNDERS = frozenset(
    {"__lt__", "__le__", "__eq__", "__ne__", "__gt__", "__ge__", "__hash__"}
)
CONTAINER_DUNDERS = frozenset(
    {
        "__len__",
        "__getitem__",
        "__setitem__",
        "__delitem__",
        "__contains__",
        "__iter__",
        "__next__",
        "__reversed__",
        "__missing__",
    }
)
CONTEXT_MANAGER_DUNDERS = frozenset({"__enter__", "__exit__", "__aenter__", "__aexit__"})
ASYNC_DUNDERS = frozenset({"__await__", "__aiter__", "__anext__"})
NUMERIC_CONVERSION_DUNDERS = frozenset(
    {
        "__complex__",
        "__int__",
        "__float__",
        "__index__",
        "__round__",
        "__trunc__",
        "__floor__",
        "__ceil__",
        "__length_hint__",
    }
)
PATH_PROTOCOL_DUNDERS = frozenset({"__fspath__"})
OTHER_SPECIAL_DUNDERS = frozenset(
    {
        "__new__",
        "__init__",
        "__del__",
        "__repr__",
        "__str__",
        "__bytes__",
        "__format__",
        "__bool__",
        "__call__",
        "__class_getitem__",
        "__init_subclass__",
        "__mro_entries__",
        "__instancecheck__",
        "__subclasscheck__",
        "__copy__",
        "__deepcopy__",
        "__reduce__",
        "__reduce_ex__",
        "__getnewargs__",
        "__getnewargs_ex__",
        "__getstate__",
        "__setstate__",
        "__sizeof__",
    }
)
PYTHON_SPECIAL_DUNDERS = (
    OPERATOR_DUNDERS
    | DESCRIPTOR_DUNDERS
    | ATTRIBUTE_ACCESS_DUNDERS
    | COMPARISON_DUNDERS
    | CONTAINER_DUNDERS
    | CONTEXT_MANAGER_DUNDERS
    | ASYNC_DUNDERS
    | NUMERIC_CONVERSION_DUNDERS
    | PATH_PROTOCOL_DUNDERS
    | OTHER_SPECIAL_DUNDERS
)
OVERLOAD_DECORATORS = frozenset({"overload", "typing.overload", "typing_extensions.overload"})
ABSTRACT_DECORATORS = frozenset(
    {
        "abstractmethod",
        "abc.abstractmethod",
        "abstractclassmethod",
        "abstractstaticmethod",
        "abstractproperty",
    }
)
PROPERTY_DECORATORS = frozenset(
    {
        "property",
        "cached_property",
        "hybrid_property",
        "declared_attr",
        "util.memoized_property",
    }
)
NAME_ROLE_GROUPS = (
    (OPERATOR_DUNDERS, FunctionSemanticRole.OPERATOR_OVERLOAD, "operator overload protocol"),
    (DESCRIPTOR_DUNDERS, FunctionSemanticRole.DESCRIPTOR_METHOD, "descriptor protocol"),
    (
        ATTRIBUTE_ACCESS_DUNDERS,
        FunctionSemanticRole.ATTRIBUTE_ACCESS_HOOK,
        "attribute access protocol",
    ),
    (COMPARISON_DUNDERS, FunctionSemanticRole.COMPARISON_PROTOCOL, "comparison protocol"),
    (CONTAINER_DUNDERS, FunctionSemanticRole.CONTAINER_PROTOCOL, "container protocol"),
    (
        CONTEXT_MANAGER_DUNDERS,
        FunctionSemanticRole.CONTEXT_MANAGER_PROTOCOL,
        "context manager protocol",
    ),
    (ASYNC_DUNDERS, FunctionSemanticRole.ASYNC_PROTOCOL, "async protocol"),
)
SIMPLE_FORWARDER_MAX_BODY_LINES = 5
PYTHON_PATH_ROLE_OPTIONS = PathSemanticRoleOptions(
    generated_path_parts=("_cython",),
    generated_name_markers=("generated", "_cy.py"),
    test_name_prefixes=("test_",),
    test_name_suffixes=("_test.py", "_tests.py", "tests.py"),
)


def classify_python_semantic_roles(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    file_path: str,
    repository_role: str,
    body_line_count: int,
) -> FunctionSemanticRoles:
    """Classify Python-specific semantic surfaces during extraction.

    Assessment code consumes only the resulting role strings. Keeping dunder,
    decorator, and AST-shape rules here prevents Python protocol knowledge from
    leaking into language-neutral scoring policy.
    """

    roles: set[FunctionSemanticRole] = set()
    reasons: list[str] = []
    _add_name_roles(node.name, roles, reasons)
    path_roles = path_semantic_roles(
        file_path,
        repository_role,
        PYTHON_PATH_ROLE_OPTIONS,
    )
    roles.update(FunctionSemanticRole(role) for role in path_roles.roles)
    reasons.extend(path_roles.reasons)

    decorators = frozenset(_decorator_name(item) for item in node.decorator_list)
    if _decorators_match(decorators, OVERLOAD_DECORATORS):
        roles.add(FunctionSemanticRole.TYPING_OVERLOAD)
        reasons.append("typing overload declarations describe interface shape, not reusable logic")
    if _decorators_match(decorators, ABSTRACT_DECORATORS):
        roles.add(FunctionSemanticRole.ABSTRACT_OR_INTERFACE_STUB)
        reasons.append("abstract declarations describe interface shape, not reusable logic")
    if _decorators_match(decorators, PROPERTY_DECORATORS):
        roles.add(FunctionSemanticRole.PROPERTY_ACCESSOR)
        reasons.append("property-like accessors are public API surfaces")
    if _abstract_or_interface_stub(node):
        roles.add(FunctionSemanticRole.ABSTRACT_OR_INTERFACE_STUB)
        reasons.append("stub bodies are interface evidence, not refactorable implementation")
    if (forwarded_call := _simple_forwarder_call(node, body_line_count)) is not None:
        roles.add(FunctionSemanticRole.ADAPTER_FORWARDER)
        reasons.append("single-call delegation is usually API topology")
        if _public_api_symbol(node.name) and _call_is_same_name_delegate(
            forwarded_call,
            node.name,
        ):
            roles.add(FunctionSemanticRole.PUBLIC_API_MIRROR)
            reasons.append("public delegation mirrors another API surface")

    if not roles:
        roles.add(FunctionSemanticRole.NORMAL_FUNCTION)

    return FunctionSemanticRoles(
        roles=tuple(sorted(role.value for role in roles)),
        reasons=tuple(reasons),
    )


def _add_name_roles(
    name: str,
    roles: set[FunctionSemanticRole],
    reasons: list[str],
) -> None:
    if name == "__init__":
        roles.add(FunctionSemanticRole.CONSTRUCTOR)
        reasons.append("constructor methods usually own object setup boundaries")
    if name in PYTHON_SPECIAL_DUNDERS:
        roles.add(FunctionSemanticRole.PYTHON_SPECIAL_METHOD)
        reasons.append("known Python special method required by protocol semantics")
    elif DUNDER_RE.match(name):
        roles.add(FunctionSemanticRole.CUSTOM_DUNDER_OR_FRAMEWORK_HOOK)
        reasons.append("custom dunder names often denote framework hooks")
    for names, role, reason in NAME_ROLE_GROUPS:
        if name in names:
            roles.add(role)
            reasons.append(reason)


def _decorator_name(node: ast.AST) -> str:
    if type(node) is ast.Name:
        return node.id
    if type(node) is ast.Attribute:
        parent = _decorator_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if type(node) is ast.Call:
        return _decorator_name(node.func)
    return ""


def _decorators_match(decorators: frozenset[str], known: frozenset[str]) -> bool:
    return any(_matches_decorator(name, known) for name in decorators if name)


def _matches_decorator(name: str, known: frozenset[str]) -> bool:
    return name in known or any(
        name.endswith(f".{item}") or name.startswith(f"{item}.") or f".{item}." in name
        for item in known
    )


def _abstract_or_interface_stub(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    statements = _body_without_docstring(node.body)
    if len(statements) != 1:
        return False
    statement = statements[0]
    if type(statement) is ast.Pass:
        return True
    if type(statement) is ast.Expr and type(statement.value) is ast.Constant:
        return statement.value.value is Ellipsis
    if type(statement) is ast.Raise:
        return _raises_not_implemented(statement)
    if type(statement) is ast.Return:
        return type(statement.value) is ast.Name and statement.value.id == "NotImplemented"
    return False


def _body_without_docstring(statements: list[ast.stmt]) -> list[ast.stmt]:
    if (
        statements
        and type(statements[0]) is ast.Expr
        and type(statements[0].value) is ast.Constant
        and type(statements[0].value.value) is str
    ):
        return statements[1:]
    return statements


def _raises_not_implemented(statement: ast.Raise) -> bool:
    exc = statement.exc
    if type(exc) is ast.Call:
        exc = exc.func
    return type(exc) is ast.Name and exc.id == "NotImplementedError"


def _simple_forwarder_call(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    body_line_count: int,
) -> ast.Call | None:
    if body_line_count > SIMPLE_FORWARDER_MAX_BODY_LINES:
        return None
    statements = _body_without_docstring(node.body)
    if len(statements) != 1:
        return None
    statement = statements[0]
    expr = (
        cast(ast.Return | ast.Expr, statement).value
        if type(statement) in {ast.Return, ast.Expr}
        else None
    )
    unwrapped: ast.AST | None = _unwrap_await(expr)
    if type(unwrapped) is not ast.Call:
        return None
    return unwrapped if _call_is_delegate_attribute(unwrapped) else None


def _unwrap_await(expr: ast.AST | None) -> ast.AST | None:
    return expr.value if type(expr) is ast.Await else expr


def _public_api_symbol(name: str) -> bool:
    return not name.startswith("_")


def _call_is_delegate_attribute(call: ast.Call) -> bool:
    func = call.func
    if type(func) is not ast.Attribute:
        return False
    receiver = func.value
    return type(receiver) is ast.Attribute and _root_name(receiver) == "self"


def _call_is_same_name_delegate(call: ast.Call, name: str) -> bool:
    func = call.func
    return type(func) is ast.Attribute and func.attr == name and _call_is_delegate_attribute(call)


def _root_name(node: ast.AST) -> str:
    current = node
    while type(current) is ast.Attribute:
        current = current.value
    return current.id if type(current) is ast.Name else ""


__all__ = ["classify_python_semantic_roles"]
