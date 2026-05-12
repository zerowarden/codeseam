from __future__ import annotations

import pytest

from codeseam.adapters.languages.ecmascript.semantic_roles import (
    FunctionRoleContext,
    JsTsRoleClassifierOptions,
    classify_function_roles,
)
from codeseam.analysis import FunctionSemanticRole


@pytest.mark.parametrize(
    ("context", "expected_roles"),
    (
        (
            FunctionRoleContext(
                file_path="src/service.ts",
                repository_role="source",
                syntax_kind="function_declaration",
                symbol="loadRecords",
                raw_signature="function loadRecords(): Records",
                body_text="{ return loadRecordsFromStore(); }",
                body_line_count=3,
            ),
            {FunctionSemanticRole.NORMAL_FUNCTION},
        ),
        (
            FunctionRoleContext(
                file_path="src/service.spec.mts",
                repository_role="source",
                syntax_kind="function_declaration",
                symbol="loadRecords",
                raw_signature="function loadRecords(): Records",
                body_text="{ return loadRecordsFromStore(); }",
                body_line_count=3,
            ),
            {FunctionSemanticRole.TEST_CODE},
        ),
        (
            FunctionRoleContext(
                file_path=".pnp.cjs",
                repository_role="source",
                syntax_kind="function_declaration",
                symbol="setup",
                raw_signature="function setup(): void",
                body_text="{ return setupRuntime(); }",
                body_line_count=3,
            ),
            {FunctionSemanticRole.GENERATED_OR_CYTHON_BOUNDARY},
        ),
        (
            FunctionRoleContext(
                file_path="src/service.ts",
                repository_role="source",
                syntax_kind="method_signature",
                symbol="execute",
                raw_signature="execute(input: string): Result",
                body_text="",
                body_line_count=1,
                is_overload_signature=True,
            ),
            {
                FunctionSemanticRole.ABSTRACT_OR_INTERFACE_STUB,
                FunctionSemanticRole.DECLARATION_BOUNDARY,
                FunctionSemanticRole.OVERLOAD_SIGNATURE,
            },
        ),
        (
            FunctionRoleContext(
                file_path="src/service.ts",
                repository_role="source",
                syntax_kind="method_definition",
                symbol="query",
                raw_signature="query(path: string): Result",
                body_text="opaque structured tree",
                body_line_count=20,
                is_simple_forwarder=True,
            ),
            {
                FunctionSemanticRole.ADAPTER_FORWARDER,
            },
        ),
    ),
)
def test_ecmascript_semantic_role_table(
    context: FunctionRoleContext,
    expected_roles: set[str],
) -> None:
    assert set(classify_function_roles(context).roles) == expected_roles


def test_ecmascript_framework_connector_symbols_are_configurable() -> None:
    context = FunctionRoleContext(
        file_path="src/service.ts",
        repository_role="source",
        syntax_kind="function_declaration",
        symbol="selectRuntimeState",
        raw_signature="function selectRuntimeState(state: State): View",
        body_text="{ return { value: state.value }; }",
        body_line_count=3,
    )

    roles = classify_function_roles(
        context,
        JsTsRoleClassifierOptions(framework_connector_symbols=frozenset({"selectRuntimeState"})),
    ).roles

    assert set(roles) == {FunctionSemanticRole.FRAMEWORK_CONNECTOR}
