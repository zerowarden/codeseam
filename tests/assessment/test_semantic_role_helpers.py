from __future__ import annotations

import pytest

from codeseam.analysis import (
    API_SURFACE_ROLES,
    INTERFACE_ONLY_ROLES,
    FunctionSemanticRole,
    PathSemanticRoleOptions,
    async_path,
    path_semantic_roles,
    sync_async_mirror_members,
    sync_async_mirror_pair,
)


@pytest.mark.parametrize(
    "path",
    (
        "packages/app/integration-tests/models/page.ts",
        "packages/server/src/utils/testing/apiUtils.ts",
    ),
)
def test_path_semantic_roles_classifies_test_topology_variants(path: str) -> None:
    roles = path_semantic_roles(path, "source").roles

    assert FunctionSemanticRole.TEST_CODE in roles


def test_generic_path_semantic_roles_do_not_know_ecmascript_tooling_names() -> None:
    roles = path_semantic_roles(".pnp.cjs", "source").roles

    assert FunctionSemanticRole.GENERATED_OR_CYTHON_BOUNDARY not in roles


@pytest.mark.parametrize(
    "path",
    (
        "src/ext/asyncio/session.py",
        "src/drivers/asyncpg.py",
        "src/core/async_engine.py",
    ),
)
def test_async_path_uses_generic_tokens_and_prefixes(path: str) -> None:
    assert async_path(path)


def test_async_path_allows_configured_extra_markers() -> None:
    assert async_path("src/drivers/aiomysql.py", extra_markers=("aiomysql",))


def test_sync_async_mirror_pair_uses_symbol_and_path_not_language_syntax() -> None:
    assert sync_async_mirror_pair(
        left_symbol="execute",
        left_file="src/engine/session.py",
        right_symbol="execute",
        right_file="src/asyncio/session.py",
    )


def test_sync_async_mirror_pair_requires_matching_symbol() -> None:
    assert not sync_async_mirror_pair(
        left_symbol="execute",
        left_file="src/engine/session.py",
        right_symbol="run",
        right_file="src/asyncio/session.py",
    )


def test_sync_async_mirror_members_detects_matching_symbol_across_group() -> None:
    assert sync_async_mirror_members(
        (
            ("connect", "lib/core/engine.py"),
            ("connect", "lib/asyncio/engine.py"),
            ("close", "lib/core/engine.py"),
        )
    )


def test_typescript_declaration_roles_are_interface_only_guardrails() -> None:
    roles = path_semantic_roles(
        "types/service.d.ts",
        "source",
        PathSemanticRoleOptions(declaration_suffixes=(".d.ts",)),
    ).roles

    assert FunctionSemanticRole.DECLARATION_BOUNDARY in roles
    assert FunctionSemanticRole.DECLARATION_BOUNDARY.value in INTERFACE_ONLY_ROLES
    assert FunctionSemanticRole.OVERLOAD_SIGNATURE.value in INTERFACE_ONLY_ROLES


@pytest.mark.parametrize(
    "role",
    (
        FunctionSemanticRole.FRAMEWORK_CONNECTOR,
        FunctionSemanticRole.FRAMEWORK_RENDER_SURFACE,
        FunctionSemanticRole.FRAMEWORK_HOOK,
        FunctionSemanticRole.IMPLEMENTATION_CONTRACT_METHOD,
    ),
)
def test_framework_surface_roles_are_api_surface_guardrails(
    role: FunctionSemanticRole,
) -> None:
    assert role.value in API_SURFACE_ROLES
