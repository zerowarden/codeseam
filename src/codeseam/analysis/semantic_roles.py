from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import PurePosixPath

ASYNC_PATH_MARKERS = frozenset({"async", "asyncio", "asynchronous"})
PATH_TOKEN_RE = re.compile(r"[-_.]+")
RoleLabel = str


class FunctionSemanticRole(StrEnum):
    """Language-neutral role labels used as actionability guardrails.

    These roles do not say whether a relation is real. They describe semantic
    surfaces where structural similarity is often required by a protocol,
    framework boundary, or API mirror, so edit recommendations should be capped
    unless stronger non-trivial body evidence exists.
    """

    ABSTRACT_OR_INTERFACE_STUB = "abstract_or_interface_stub"
    ADAPTER_FORWARDER = "adapter_forwarder"
    ASYNC_PROTOCOL = "async_protocol"
    ATTRIBUTE_ACCESS_HOOK = "attribute_access_hook"
    COMMAND_OR_REGISTRY_SURFACE = "command_or_registry_surface"
    COMPARISON_PROTOCOL = "comparison_protocol"
    CONSTRUCTOR = "constructor"
    CONTAINER_PROTOCOL = "container_protocol"
    CONTEXT_MANAGER_PROTOCOL = "context_manager_protocol"
    CUSTOM_DUNDER_OR_FRAMEWORK_HOOK = "custom_dunder_or_framework_hook"
    DECLARATION_BOUNDARY = "declaration_boundary"
    DESCRIPTOR_METHOD = "descriptor_method"
    EXAMPLE_CODE = "example_code"
    FRAMEWORK_CONNECTOR = "framework_connector"
    FRAMEWORK_HOOK = "framework_hook"
    FRAMEWORK_RENDER_SURFACE = "framework_render_surface"
    GENERATED_OR_CYTHON_BOUNDARY = "generated_or_cython_boundary"
    IMPLEMENTATION_CONTRACT_METHOD = "implementation_contract_method"
    NORMAL_FUNCTION = "normal_function"
    OPERATOR_OVERLOAD = "operator_overload"
    OVERLOAD_SIGNATURE = "overload_signature"
    PREDICATE_BOUNDARY = "predicate_boundary"
    PROPERTY_ACCESSOR = "property_accessor"
    PUBLIC_API_MIRROR = "public_api_mirror"
    PYTHON_SPECIAL_METHOD = "python_special_method"
    SYNC_ASYNC_MIRROR = "sync_async_mirror"
    TEST_CODE = "test_code"
    TYPING_OVERLOAD = "typing_overload"


INTERFACE_ONLY_ROLES: frozenset[RoleLabel] = frozenset(
    role.value
    for role in (
        FunctionSemanticRole.TYPING_OVERLOAD,
        FunctionSemanticRole.OVERLOAD_SIGNATURE,
        FunctionSemanticRole.ABSTRACT_OR_INTERFACE_STUB,
        FunctionSemanticRole.DECLARATION_BOUNDARY,
    )
)
DECLARATION_SURFACE_ROLES: frozenset[RoleLabel] = frozenset(
    role.value
    for role in (
        FunctionSemanticRole.OVERLOAD_SIGNATURE,
        FunctionSemanticRole.DECLARATION_BOUNDARY,
    )
)
PROTOCOL_SURFACE_ROLES: frozenset[RoleLabel] = frozenset(
    role.value
    for role in (
        FunctionSemanticRole.OPERATOR_OVERLOAD,
        FunctionSemanticRole.DESCRIPTOR_METHOD,
        FunctionSemanticRole.ATTRIBUTE_ACCESS_HOOK,
        FunctionSemanticRole.CONTAINER_PROTOCOL,
        FunctionSemanticRole.COMPARISON_PROTOCOL,
        FunctionSemanticRole.CONTEXT_MANAGER_PROTOCOL,
        FunctionSemanticRole.ASYNC_PROTOCOL,
        FunctionSemanticRole.PROPERTY_ACCESSOR,
    )
)
API_SURFACE_ROLES: frozenset[RoleLabel] = frozenset(
    role.value
    for role in (
        FunctionSemanticRole.ADAPTER_FORWARDER,
        FunctionSemanticRole.PUBLIC_API_MIRROR,
        FunctionSemanticRole.SYNC_ASYNC_MIRROR,
        FunctionSemanticRole.COMMAND_OR_REGISTRY_SURFACE,
        FunctionSemanticRole.IMPLEMENTATION_CONTRACT_METHOD,
        FunctionSemanticRole.FRAMEWORK_CONNECTOR,
        FunctionSemanticRole.FRAMEWORK_RENDER_SURFACE,
        FunctionSemanticRole.FRAMEWORK_HOOK,
        FunctionSemanticRole.GENERATED_OR_CYTHON_BOUNDARY,
    )
)


@dataclass(frozen=True, slots=True)
class FunctionSemanticRoles:
    roles: tuple[RoleLabel, ...]
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PathSemanticRoleOptions:
    generated_path_parts: tuple[str, ...] = ()
    generated_name_markers: tuple[str, ...] = ()
    test_name_prefixes: tuple[str, ...] = ()
    test_name_suffixes: tuple[str, ...] = ()
    declaration_suffixes: tuple[str, ...] = ()


DEFAULT_PATH_SEMANTIC_ROLE_OPTIONS = PathSemanticRoleOptions()


COMMON_GENERATED_PATH_PARTS = frozenset(
    {
        ".yarn",
        "build",
        "coverage",
        "dist",
        "gen",
        "generated",
        "node_modules",
        "third-party",
        "third_party",
        "vendor",
    }
)

COMMON_TEST_PATH_PART_PATTERNS = (
    r"__tests__",
    r"fixtures?",
    r"integration[-_]tests?",
    r"specs?",
    r"tests?",
    r"testing",
)
COMMON_TEST_PATH_PART_RE = re.compile(rf"^(?:{'|'.join(COMMON_TEST_PATH_PART_PATTERNS)})$")
COMMON_EXAMPLE_PATH_PARTS = frozenset({"demo", "demos", "example", "examples"})


@dataclass(frozen=True, slots=True)
class PathFacts:
    path: PurePosixPath
    parts: frozenset[str]
    name: str
    stem_tokens: frozenset[str]


@lru_cache(maxsize=8192)
def path_facts(file_path: str) -> PathFacts:
    path = PurePosixPath(file_path.replace("\\", "/"))
    tokens: set[str] = set()
    for part in path.parts:
        lower = part.lower()
        stem = lower.rsplit(".", 1)[0]
        tokens.add(lower)
        tokens.add(stem)
        tokens.update(token for token in PATH_TOKEN_RE.split(stem) if token)
    return PathFacts(
        path=path,
        parts=frozenset(part.lower() for part in path.parts),
        name=path.name.lower(),
        stem_tokens=frozenset(tokens),
    )


def path_semantic_roles(
    file_path: str,
    repository_role: str,
    options: PathSemanticRoleOptions = DEFAULT_PATH_SEMANTIC_ROLE_OPTIONS,
) -> FunctionSemanticRoles:
    """Classify language-neutral path surfaces that cap edit recommendations.

    Language adapters still own syntax-specific role detection. This helper
    centralizes repository-role and path topology signals so test/example/
    generated guardrails stay consistent across native and Tree-sitter
    frontends.
    """

    return _path_semantic_roles_cached(file_path, repository_role.lower(), options)


@lru_cache(maxsize=8192)
def _path_semantic_roles_cached(
    file_path: str,
    repository_role: str,
    options: PathSemanticRoleOptions,
) -> FunctionSemanticRoles:
    facts = path_facts(file_path)
    generated_parts = COMMON_GENERATED_PATH_PARTS | frozenset(
        part.lower() for part in options.generated_path_parts
    )
    generated_markers = _lower_tuple(options.generated_name_markers)
    test_prefixes = _lower_tuple(options.test_name_prefixes)
    test_suffixes = _lower_tuple(options.test_name_suffixes)
    declaration_suffixes = _lower_tuple(options.declaration_suffixes)
    roles: list[FunctionSemanticRole] = []
    reasons: list[str] = []
    if (
        repository_role in {"generated", "vendor", "build_output"}
        or facts.parts & generated_parts
        or any(marker in facts.name for marker in generated_markers)
    ):
        _add_role(
            roles,
            reasons,
            FunctionSemanticRole.GENERATED_OR_CYTHON_BOUNDARY,
            "generated, vendored, or build-output code is not a direct edit target",
        )
    if (
        repository_role in {"test", "fixture"}
        or has_common_test_path_part(facts.parts)
        or facts.name.startswith(test_prefixes)
        or facts.name.endswith(test_suffixes)
    ):
        _add_role(
            roles,
            reasons,
            FunctionSemanticRole.TEST_CODE,
            "test or fixture code has different refactor economics",
        )
    if repository_role == "example" or facts.parts & COMMON_EXAMPLE_PATH_PARTS:
        _add_role(
            roles,
            reasons,
            FunctionSemanticRole.EXAMPLE_CODE,
            "example or demo code is often pedagogical surface area",
        )
    if facts.name.endswith(declaration_suffixes):
        roles.extend(
            (
                FunctionSemanticRole.DECLARATION_BOUNDARY,
                FunctionSemanticRole.ABSTRACT_OR_INTERFACE_STUB,
            )
        )
        reasons.append("declaration files describe API shape, not implementation logic")
    return FunctionSemanticRoles(
        roles=role_labels(roles),
        reasons=_dedupe_reasons(reasons),
    )


def role_label(role: FunctionSemanticRole | str) -> RoleLabel:
    return role.value if isinstance(role, FunctionSemanticRole) else role


def role_labels(roles: Iterable[FunctionSemanticRole | str]) -> tuple[RoleLabel, ...]:
    return tuple(dict.fromkeys(label for role in roles if (label := role_label(role))))


def role_counts(values: Iterable[FunctionSemanticRole | str]) -> dict[RoleLabel, int]:
    return dict(Counter(role_labels(values)))


def has_common_test_path_part(parts: Iterable[str]) -> bool:
    return any(COMMON_TEST_PATH_PART_RE.match(part.lower()) for part in parts)


def role_set(counts: Mapping[str, int] | None) -> frozenset[str]:
    if not counts:
        return frozenset()
    return frozenset(role for role, count in counts.items() if count > 0)


def sync_async_mirror_members(members: Iterable[tuple[str, str]]) -> bool:
    """Return whether matching symbols appear on both sync and async paths.

    This is intentionally language-neutral. Language adapters can classify
    syntax-specific async constructs, but repo topology such as `asyncio/` vs
    ordinary implementation paths is available from every member's symbol/file
    identity and belongs in analysis aggregation.
    """

    seen_symbols: dict[str, set[bool]] = {}
    for symbol, file_path in members:
        if symbol:
            seen_symbols.setdefault(symbol, set()).add(async_path(file_path))
    return any(values == {False, True} for values in seen_symbols.values())


def sync_async_mirror_pair(
    *,
    left_symbol: str,
    left_file: str,
    right_symbol: str,
    right_file: str,
) -> bool:
    if not left_symbol or left_symbol != right_symbol:
        return False
    return async_path(left_file) != async_path(right_file)


def async_path(path: str, extra_markers: Iterable[str] = ()) -> bool:
    """Return whether a path looks like an async implementation surface.

    The default rule is intentionally generic: exact path markers such as
    `asyncio/`, tokenized names such as `async_engine.py`, and `async*` stems
    such as `asyncpg.py` count as async. Framework-specific names that do not
    carry an `async` token, such as some `aio*` drivers, should be supplied by
    caller configuration through `extra_markers` rather than hardcoded here.
    """

    facts = path_facts(path)
    markers = ASYNC_PATH_MARKERS | frozenset(marker.lower() for marker in extra_markers)
    return bool(facts.stem_tokens & markers) or any(
        token.startswith("async") for token in facts.stem_tokens
    )


def _add_role(
    roles: list[FunctionSemanticRole],
    reasons: list[str],
    role: FunctionSemanticRole,
    reason: str,
) -> None:
    roles.append(role)
    reasons.append(reason)


def _dedupe_reasons(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _lower_tuple(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(value.lower() for value in values)


__all__ = [
    "ASYNC_PATH_MARKERS",
    "API_SURFACE_ROLES",
    "COMMON_EXAMPLE_PATH_PARTS",
    "COMMON_GENERATED_PATH_PARTS",
    "COMMON_TEST_PATH_PART_RE",
    "DECLARATION_SURFACE_ROLES",
    "DEFAULT_PATH_SEMANTIC_ROLE_OPTIONS",
    "FunctionSemanticRole",
    "FunctionSemanticRoles",
    "INTERFACE_ONLY_ROLES",
    "PathFacts",
    "PathSemanticRoleOptions",
    "PROTOCOL_SURFACE_ROLES",
    "RoleLabel",
    "async_path",
    "has_common_test_path_part",
    "path_facts",
    "path_semantic_roles",
    "role_counts",
    "role_label",
    "role_labels",
    "role_set",
    "sync_async_mirror_members",
    "sync_async_mirror_pair",
]
