from __future__ import annotations

import pytest
import tree_sitter_typescript as tstypescript
from tree_sitter import Language, Node

from codeseam.adapters.languages.ecmascript.runtime import TreeSitterRuntime, iter_named_nodes
from codeseam.adapters.languages.ecmascript.semantic_roles import (
    FunctionRoleContext,
    JsTsRoleClassifierOptions,
    classify_function_roles,
    delegating_call,
    trivial_body,
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
                repository_role="test",
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


TYPESCRIPT = TreeSitterRuntime.from_language(
    "typescript", Language(tstypescript.language_typescript())
)
FUNCTION_TYPES = frozenset({"arrow_function", "function_declaration", "method_definition"})


def _function_body(source: str) -> Node | None:
    root = TYPESCRIPT.parse(source.encode()).root_node
    node = next(item for item in iter_named_nodes(root) if item.type in FUNCTION_TYPES)
    return node.child_by_field_name("body")


@pytest.mark.parametrize(
    ("source", "trivial"),
    [
        ("function size(): number { return 0; }", True),
        ("function clear(): void {}", True),
        ("function done(): void { return; }", True),
        ('const debug = (event: string) => log("debug", event, ...rest);', True),
        ("class A { name(): string { return this._name!; } }", True),
        ("class A { first(): T { return this.items[0] as T; } }", True),
        ("async function load(id: string) { return await this.client.fetch(id); }", True),
        ("class A { set(v: number) { this._value = v; } }", True),
        ("const make = (x: number) => new Point(x, 0);", True),
        ("const label = () => `ready`;", True),
        ("const label = (x: string) => `item ${x}`;", False),
        ("const score = (t: string) => Base.score(t) - 0.05;", False),
        ('const name = (e: unknown) => e instanceof Error ? e.name : "Error";', False),
        ("function load(id: string) { return parse(fetch(id)); }", False),
        ("function load(id: string) { const row = fetch(id); return row; }", False),
    ],
)
def test_one_operation_bodies_are_trivial(source: str, trivial: bool) -> None:
    assert trivial_body(_function_body(source)) is trivial


@pytest.mark.parametrize(
    ("source", "forwarder"),
    [
        ("class A { add(h: H, p: string) { return this.controller(h).addScript(p); } }", True),
        ("function on(e: string, cb: L) { eventManager.on(e, cb); }", True),
        ("const emit = (e: E) => bus.emit(e);", True),
        ('function run() { console.log("start"); const r = work(); return r; }', False),
        ("function load(id: string) { return fetch(id); }", False),
    ],
    ids=["this-member", "module-member", "arrow", "logging-then-work", "plain-call"],
)
def test_forwarders_are_one_member_call(source: str, forwarder: bool) -> None:
    assert delegating_call(_function_body(source)) is forwarder
