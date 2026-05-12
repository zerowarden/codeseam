from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from codeseam.analysis import (
    FunctionSemanticRole,
    FunctionSemanticRoles,
    PathSemanticRoleOptions,
    path_semantic_roles,
)

SIMPLE_FORWARDER_MAX_BODY_LINES = 6
DECLARATION_TYPES = frozenset({"function_signature", "method_signature"})
DECLARATION_SUFFIXES = (".d.ts", ".d.mts", ".d.cts")
JS_TS_EXTENSIONS = (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts")
GENERATED_NAME_MARKERS = (".pnp.",)
TEST_NAME_STEMS = (".test", ".spec")
TEST_NAME_SUFFIXES = tuple(
    f"{stem}{extension}" for stem in TEST_NAME_STEMS for extension in JS_TS_EXTENSIONS
)
SIMPLE_FORWARDER_RE = re.compile(
    r"^\s*\{\s*(?:return\s+)?(?:await\s+)?(?:this|[A-Za-z_$][\w$]*)\.",
    re.DOTALL,
)
SIMPLE_RETURN_BODY_RE = re.compile(
    r"^\s*(?:\{\s*return\s+[^{};]+;?\s*\}|[^{};]+)\s*$",
    re.DOTALL,
)
PREDICATE_SYMBOL_RE = re.compile(r"^(?:is|has|can|should|supports|allows|needs)[A-Z0-9]")
CONTRACT_SYMBOL_RE = re.compile(r"^(?:init|create|get)[A-Z0-9]|^(?:name|tableName|type)$")
DEFAULT_FRAMEWORK_CONNECTOR_SYMBOLS = frozenset(
    {
        "mapDispatchToProps",
        "mapStateToProps",
        "mergeProps",
    }
)
COMMAND_REGISTRY_SYMBOL_RE = re.compile(
    r"^(?:runtime|register[A-Z0-9_].*|create[A-Z0-9_].*(?:Command|Action|Handler)|.*Command)$"
)
COMMAND_REGISTRY_RETURN_RE = re.compile(
    r":\s*[^=]*\b(?:Command|Action|Registry|Handler|Runtime|Declaration|Descriptor)\b"
)
COMMAND_REGISTRY_BODY_RE = re.compile(
    r"\b(?:execute|handler|command|commands|name|label|description)\s*:"
)
COMMAND_REGISTRY_CALL_RE = re.compile(
    r"\.(?:register|add|execute|dispatch)(?:Command|Action|Handler)?\s*\("
)


@dataclass(frozen=True, slots=True)
class FunctionRoleContext:
    file_path: str
    repository_role: str
    syntax_kind: str
    symbol: str
    raw_signature: str
    body_text: str
    body_line_count: int
    is_overload_signature: bool = False
    has_jsx_body: bool = False
    has_hook_call: bool = False
    returns_jsx: bool = False
    is_simple_forwarder: bool = False
    is_simple_return_body: bool = False
    has_command_descriptor_keys: bool = False
    has_command_registry_call: bool = False


@dataclass(frozen=True, slots=True)
class JsTsRoleClassifierOptions:
    framework_connector_symbols: frozenset[str] = DEFAULT_FRAMEWORK_CONNECTOR_SYMBOLS


DEFAULT_ROLE_CLASSIFIER_OPTIONS = JsTsRoleClassifierOptions()
ECMASCRIPT_PATH_ROLE_OPTIONS = PathSemanticRoleOptions(
    generated_name_markers=GENERATED_NAME_MARKERS,
    test_name_suffixes=TEST_NAME_SUFFIXES,
    declaration_suffixes=DECLARATION_SUFFIXES,
)


@dataclass(frozen=True, slots=True)
class FunctionRoleFacts:
    """Derived syntax facts used by the rule table.

    Tree-sitter extraction can supply structured booleans on FunctionRoleContext
    as it grows. Regex checks here are fallback priors over already-extracted
    text, so the classifier remains cheap and independent of compiler APIs.
    """

    is_declaration_signature: bool
    is_abstract_signature: bool
    is_overload_signature: bool
    is_small_body: bool
    is_property_accessor: bool
    is_simple_return: bool
    is_predicate_name: bool
    is_contract_name: bool
    has_boolean_return: bool
    has_visibility_or_override_modifier: bool
    is_render_surface: bool
    is_hook_surface: bool
    is_framework_connector: bool
    is_command_or_registry_surface: bool
    is_tiny_contract_like_method: bool
    is_tiny_predicate_boundary: bool
    is_simple_forwarder: bool
    is_same_name_forwarder: bool


RolePredicate = Callable[[FunctionRoleContext, FunctionRoleFacts], bool]


@dataclass(frozen=True, slots=True)
class RoleRule:
    predicate: RolePredicate
    roles: tuple[FunctionSemanticRole, ...]
    reason: str


SURFACE_RULES: tuple[RoleRule, ...] = (
    RoleRule(
        lambda context, _facts: context.symbol == "constructor",
        (FunctionSemanticRole.CONSTRUCTOR,),
        "constructors usually share setup helpers rather than whole methods",
    ),
    RoleRule(
        lambda _context, facts: facts.is_property_accessor,
        (FunctionSemanticRole.PROPERTY_ACCESSOR,),
        "get/set accessors are protocol-like API surface",
    ),
    RoleRule(
        lambda _context, facts: facts.is_render_surface,
        (FunctionSemanticRole.FRAMEWORK_RENDER_SURFACE,),
        "render/component surfaces are framework API boundaries",
    ),
    RoleRule(
        lambda _context, facts: facts.is_hook_surface,
        (FunctionSemanticRole.FRAMEWORK_HOOK,),
        "hook-like functions are framework lifecycle boundaries",
    ),
    RoleRule(
        lambda _context, facts: facts.is_framework_connector,
        (FunctionSemanticRole.FRAMEWORK_CONNECTOR,),
        "framework connector functions adapt application state to API shape",
    ),
    RoleRule(
        lambda _context, facts: facts.is_command_or_registry_surface,
        (FunctionSemanticRole.COMMAND_OR_REGISTRY_SURFACE,),
        "command or registry surfaces are API topology, not ordinary helpers",
    ),
    RoleRule(
        lambda _context, facts: facts.is_tiny_contract_like_method,
        (FunctionSemanticRole.IMPLEMENTATION_CONTRACT_METHOD,),
        "small methods defining implementation contracts are API surface",
    ),
    RoleRule(
        lambda _context, facts: facts.is_tiny_predicate_boundary,
        (FunctionSemanticRole.PREDICATE_BOUNDARY,),
        "small predicate helpers often encode separate intent boundaries",
    ),
)

FORWARDER_RULES: tuple[RoleRule, ...] = (
    RoleRule(
        lambda _context, facts: facts.is_simple_forwarder,
        (FunctionSemanticRole.ADAPTER_FORWARDER,),
        "small method forwards to another object or controller",
    ),
    RoleRule(
        lambda _context, facts: facts.is_same_name_forwarder,
        (FunctionSemanticRole.PUBLIC_API_MIRROR,),
        "public method mirrors a same-name downstream operation",
    ),
)


def classify_function_roles(
    context: FunctionRoleContext,
    options: JsTsRoleClassifierOptions = DEFAULT_ROLE_CLASSIFIER_OPTIONS,
) -> FunctionSemanticRoles:
    """Classify JS/TS surfaces that should cap edit recommendations.

    This is intentionally syntax-and-path based. It does not pretend to know
    TypeScript symbols; it supplies conservative guardrail roles until optional
    compiler enrichment can prove API ownership and overload bindings.
    """

    roles: set[str] = set()
    reasons: list[str] = []
    facts = role_facts(context, options)
    _add_path_roles(context, roles, reasons)
    _add_declaration_roles(context, facts, roles, reasons)
    _apply_rules(context, facts, SURFACE_RULES, roles, reasons)
    _apply_rules(context, facts, FORWARDER_RULES, roles, reasons)
    if not roles:
        roles.add(FunctionSemanticRole.NORMAL_FUNCTION)
    return FunctionSemanticRoles(
        roles=tuple(sorted(roles)),
        reasons=tuple(dict.fromkeys(reasons)),
    )


def role_facts(
    context: FunctionRoleContext,
    options: JsTsRoleClassifierOptions = DEFAULT_ROLE_CLASSIFIER_OPTIONS,
) -> FunctionRoleFacts:
    is_small_body = context.body_line_count <= SIMPLE_FORWARDER_MAX_BODY_LINES
    is_property_accessor = _property_accessor(context.raw_signature)
    is_simple_return = context.is_simple_return_body or _simple_return_body(context.body_text)
    is_predicate_name = bool(PREDICATE_SYMBOL_RE.match(context.symbol))
    is_contract_name = bool(CONTRACT_SYMBOL_RE.match(context.symbol))
    has_boolean_return = bool(re.search(r":\s*boolean\b", context.raw_signature))
    has_visibility_or_override_modifier = bool(
        re.search(r"\b(?:override|protected|public|static)\b", context.raw_signature)
    )
    is_abstract_signature = (
        context.syntax_kind == "abstract_method_signature"
        or _abstract_signature(context.raw_signature)
    )
    is_simple_forwarder = bool(
        context.is_simple_forwarder
        or (context.body_text and is_small_body and _simple_forwarder(context.body_text))
    )
    return FunctionRoleFacts(
        is_declaration_signature=context.syntax_kind in DECLARATION_TYPES,
        is_abstract_signature=is_abstract_signature,
        is_overload_signature=context.is_overload_signature,
        is_small_body=is_small_body,
        is_property_accessor=is_property_accessor,
        is_simple_return=is_simple_return,
        is_predicate_name=is_predicate_name,
        is_contract_name=is_contract_name,
        has_boolean_return=has_boolean_return,
        has_visibility_or_override_modifier=has_visibility_or_override_modifier,
        is_render_surface=_render_surface(context),
        is_hook_surface=_hook_surface(context),
        is_framework_connector=context.symbol in options.framework_connector_symbols,
        is_command_or_registry_surface=_command_or_registry_surface(context),
        is_tiny_contract_like_method=_tiny_contract_like_method(
            context,
            is_property_accessor=is_property_accessor,
            is_simple_return=is_simple_return,
            has_contract_marker=(
                is_predicate_name or is_contract_name or has_visibility_or_override_modifier
            ),
        ),
        is_tiny_predicate_boundary=_tiny_predicate_boundary(
            context,
            is_simple_return=is_simple_return,
            is_predicate_name=is_predicate_name,
            has_boolean_return=has_boolean_return,
        ),
        is_simple_forwarder=is_simple_forwarder,
        is_same_name_forwarder=is_simple_forwarder
        and _same_name_forwarder(context.symbol, context.body_text),
    )


def _apply_rules(
    context: FunctionRoleContext,
    facts: FunctionRoleFacts,
    rules: tuple[RoleRule, ...],
    roles: set[str],
    reasons: list[str],
) -> None:
    for rule in rules:
        if rule.predicate(context, facts):
            roles.update(rule.roles)
            reasons.append(rule.reason)


def _add_path_roles(
    context: FunctionRoleContext,
    roles: set[str],
    reasons: list[str],
) -> None:
    path_roles = path_semantic_roles(
        context.file_path,
        context.repository_role,
        ECMASCRIPT_PATH_ROLE_OPTIONS,
    )
    roles.update(path_roles.roles)
    reasons.extend(path_roles.reasons)


def _add_declaration_roles(
    context: FunctionRoleContext,
    facts: FunctionRoleFacts,
    roles: set[str],
    reasons: list[str],
) -> None:
    if not (
        facts.is_declaration_signature or facts.is_overload_signature or facts.is_abstract_signature
    ):
        return

    roles.add(FunctionSemanticRole.DECLARATION_BOUNDARY)
    if facts.is_overload_signature:
        roles.add(FunctionSemanticRole.OVERLOAD_SIGNATURE)
        roles.add(FunctionSemanticRole.ABSTRACT_OR_INTERFACE_STUB)
        reasons.append("overload signatures describe call shapes, not implementation logic")
        return

    if facts.is_abstract_signature:
        roles.add(FunctionSemanticRole.ABSTRACT_OR_INTERFACE_STUB)
        reasons.append("abstract declarations describe interface shape, not implementation logic")
        return

    roles.add(FunctionSemanticRole.ABSTRACT_OR_INTERFACE_STUB)
    reasons.append("declaration signatures describe API shape, not implementation logic")


def _property_accessor(raw_signature: str) -> bool:
    return bool(
        re.match(
            r"^(?:public|private|protected|static|async|\s)*\s*(?:get|set)\s+",
            raw_signature,
        )
    )


def _abstract_signature(raw_signature: str) -> bool:
    return bool(re.match(r"^(?:public|private|protected|\s)*abstract\b", raw_signature))


def _render_surface(context: FunctionRoleContext) -> bool:
    return (
        (context.has_jsx_body and bool(context.symbol) and context.symbol[0].isupper())
        or context.returns_jsx
        or _returns_jsx(context.raw_signature)
    )


def _returns_jsx(raw_signature: str) -> bool:
    return bool(
        re.search(
            r":\s*(?:JSX\.)?Element(?:\b|<)|:\s*React(?:\.[A-Za-z]+)?Element",
            raw_signature,
        )
    )


def _hook_surface(context: FunctionRoleContext) -> bool:
    return bool(context.has_hook_call and re.match(r"^use[A-Z0-9]", context.symbol))


def _tiny_contract_like_method(
    context: FunctionRoleContext,
    *,
    is_property_accessor: bool,
    is_simple_return: bool,
    has_contract_marker: bool,
) -> bool:
    """Return whether a tiny method looks like an implementation contract.

    Class and object-model hierarchies often require repeated tiny methods such
    as `hasUuid()` or `tableName()` to define local API behavior. These are real
    relations, but direct consolidation would usually erase an intentional
    override boundary. We keep this syntax-only and conservative: method
    definition, small simple return body, and a contract-like name or modifier.
    """

    return (
        context.syntax_kind == "method_definition"
        and context.symbol != "constructor"
        and not is_property_accessor
        and context.body_line_count <= SIMPLE_FORWARDER_MAX_BODY_LINES
        and is_simple_return
        and has_contract_marker
    )


def _tiny_predicate_boundary(
    context: FunctionRoleContext,
    *,
    is_simple_return: bool,
    is_predicate_name: bool,
    has_boolean_return: bool,
) -> bool:
    return (
        is_predicate_name
        and context.body_line_count <= SIMPLE_FORWARDER_MAX_BODY_LINES
        and (is_simple_return or has_boolean_return)
    )


def _simple_return_body(body_text: str) -> bool:
    return bool(body_text and SIMPLE_RETURN_BODY_RE.match(body_text))


def _simple_forwarder(body_text: str) -> bool:
    return bool(SIMPLE_FORWARDER_RE.match(body_text))


def _same_name_forwarder(symbol: str, body_text: str) -> bool:
    return bool(symbol and re.search(rf"\.{re.escape(symbol)}\s*\(", body_text))


def _command_or_registry_surface(context: FunctionRoleContext) -> bool:
    """Return whether a JS/TS callable looks like a command/API registry surface.

    This is a conservative syntax prior. We require either a command/registry
    return type plus descriptor-like object keys, or a command-registration
    symbol plus descriptor keys/calls. The assessment layer decides how strongly
    to cap the resulting role.
    """

    if not context.body_text:
        return False
    has_descriptor_keys = bool(
        context.has_command_descriptor_keys or COMMAND_REGISTRY_BODY_RE.search(context.body_text)
    )
    has_registry_call = bool(
        context.has_command_registry_call or COMMAND_REGISTRY_CALL_RE.search(context.body_text)
    )
    typed_descriptor = bool(
        COMMAND_REGISTRY_RETURN_RE.search(context.raw_signature) and has_descriptor_keys
    )
    named_registry = bool(
        COMMAND_REGISTRY_SYMBOL_RE.match(context.symbol)
        and (has_descriptor_keys or has_registry_call)
    )
    return typed_descriptor or named_registry


__all__ = [
    "FunctionRoleContext",
    "JsTsRoleClassifierOptions",
    "classify_function_roles",
    "role_facts",
]
