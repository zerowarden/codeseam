from __future__ import annotations

from functools import partial
from pathlib import Path

import pytest
from helpers import file_record
from pytest import MonkeyPatch

from codeseam.adapters.languages import (
    AdapterCapabilities,
    LanguageAdapterAnalysis,
    LanguageAnalysisContext,
    LanguageRegistry,
    RelationDetailProvider,
    RelationDetailRequest,
    RepositoryAdapterFact,
    StaticLanguageSupport,
    default_language_registry,
    relation_detail_provider,
)
from codeseam.adapters.languages.ecmascript import adapter as ecmascript
from codeseam.adapters.languages.ecmascript.compiler_facts import TypeScriptProjectFacts
from codeseam.adapters.languages.extraction import analyze_language_file
from codeseam.adapters.languages.python.adapter import PythonAstAdapter
from codeseam.analysis import (
    AdapterId,
    FunctionIR,
    FunctionSemanticRole,
    RepositoryManifest,
    RepositoryScan,
    SignatureCore,
    SignatureRecord,
    build_repository_facts,
    detect_language,
    is_analysis_language,
)
from codeseam.cache import (
    AnalysisCacheContext,
    LanguageRunCache,
    persistent_cache,
    signature_analyses_from_cache_values,
    signature_analyses_from_records,
    signature_core_cache_payload,
    signature_features_cache_payload,
    signature_output_cache_payload,
)
from codeseam.pipeline.repository_enrichment import build_repository_enrichment

LANGUAGE_FIXTURES = Path(__file__).parent / "fixtures" / "languages"
EXPECTED_ADAPTERS = {
    "Python": ("mod.py", "python_ast"),
    "TypeScript": ("mod.ts", "treesitter_ecmascript_typescript"),
    "TSX": ("mod.tsx", "treesitter_ecmascript_typescript"),
    "JavaScript": ("mod.js", "treesitter_ecmascript_typescript"),
    "JSX": ("mod.jsx", "treesitter_ecmascript_typescript"),
}
EXPECTED_CAPABILITIES = {
    "Python": ("python_ast", True, True, False, True),
    "TypeScript": ("tree_sitter", True, False, True, False),
    "TSX": ("tree_sitter", True, False, True, False),
    "JavaScript": ("tree_sitter", True, False, True, False),
    "JSX": ("tree_sitter", True, False, True, False),
}
JS_RUNTIME_EXTENSIONS = {
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".mts": "TypeScript",
    ".cts": "TypeScript",
}
JS_RUNTIME_NAMES = {
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".tsx": "tsx",
}
_file_record = partial(file_record, language="TypeScript")


def test_default_language_registry_routes_python_ast(tmp_path: Path) -> None:
    path = tmp_path / "mod.py"
    path.write_text("def run(value: str) -> str:\n    return value\n", encoding="utf-8")
    registry = default_language_registry()
    adapter = registry.adapter_for_language("Python")

    assert adapter is not None
    assert adapter.adapter_id is AdapterId.PYTHON_AST
    analysis = adapter.extract_analysis(LanguageAnalysisContext(path, "mod.py", "source", "Python"))

    assert analysis.functions[0].symbol == "run"
    assert analysis.signatures[0].symbol == "run"
    assert analysis.signatures[0].canonical_shape == "fn(str)->str"


@pytest.mark.parametrize(
    ("language", "expected"),
    EXPECTED_CAPABILITIES.items(),
)
def test_default_registry_exposes_adapter_capabilities(
    language: str,
    expected: tuple[str, bool, bool, bool, bool],
) -> None:
    adapter = default_language_registry().adapter_for_language(language)
    assert adapter is not None
    capabilities = adapter.capabilities
    syntax_frontend, relation_detail, policy_constants, repo_facts, compiler_semantics = expected

    assert capabilities.syntax_frontend == syntax_frontend
    assert capabilities.relation_detail is relation_detail
    assert capabilities.policy_constants is policy_constants
    assert capabilities.repo_facts is repo_facts
    assert capabilities.compiler_semantics is compiler_semantics


def test_repository_enrichment_calls_declared_repo_facts_provider() -> None:
    registry = LanguageRegistry([_RepoFactsAdapter()])
    facts = build_repository_facts(
        RepositoryScan(
            records=[_file_record("module.fake", language="Fake", content_hash="fake-v1")],
            selected_paths=["module.fake"],
        )
    )

    enrichment = build_repository_enrichment(facts, registry)

    assert [item.adapter_id for item in enrichment.adapter_capabilities] == [AdapterId.UNKNOWN]
    assert enrichment.adapter_facts[0].facts == {"selected_files": 1}


def test_js_ts_manifest_matchers_include_tsconfig_files() -> None:
    registry = default_language_registry()
    kinds = {
        matcher.kind
        for matcher in registry.manifest_matchers()
        if matcher.matches("packages/app/tsconfig.build.json")
    }

    assert "typescript_config" in kinds


def test_js_ts_repo_facts_provider_builds_cacheable_project_facts() -> None:
    registry = default_language_registry()
    facts = build_repository_facts(
        RepositoryScan(
            records=[
                _file_record("package.json", content_hash="pkg-v1", language="JSON"),
                _file_record("tsconfig.json", content_hash="tsconfig-v1", language="JSON"),
                _file_record("src/app.ts", content_hash="app-v1"),
                _file_record("src/view.tsx", content_hash="view-v1", language="TSX"),
                _file_record("src/types.d.ts", content_hash="types-v1"),
                _file_record("src/legacy.js", content_hash="legacy-v1", language="JavaScript"),
            ],
            selected_paths=["src/app.ts", "src/view.tsx", "src/legacy.js"],
            manifests=(
                RepositoryManifest("package.json", "node"),
                RepositoryManifest("tsconfig.json", "typescript_config"),
            ),
        )
    )

    enrichment = build_repository_enrichment(facts, registry)
    project_facts = _typescript_project_facts(enrichment.adapter_facts)

    assert sum(item.adapter_id == ecmascript.ADAPTER_ID for item in enrichment.adapter_facts) == 1
    assert project_facts.tsconfig_paths == ("tsconfig.json",)
    assert project_facts.cache_key.startswith("sha256:")


def test_js_ts_project_facts_cache_key_tracks_project_inputs() -> None:
    def project_key(tsconfig_hash: str) -> str:
        facts = build_repository_facts(
            RepositoryScan(
                records=[
                    _file_record("tsconfig.json", content_hash=tsconfig_hash, language="JSON"),
                    _file_record("src/app.ts", content_hash="app-v1"),
                ],
                selected_paths=["src/app.ts"],
                manifests=(RepositoryManifest("tsconfig.json", "typescript_config"),),
            )
        )
        enrichment = build_repository_enrichment(facts, default_language_registry())
        return _typescript_project_facts(enrichment.adapter_facts).cache_key

    assert project_key("tsconfig-v1") != project_key("tsconfig-v2")


@pytest.mark.parametrize(("suffix", "language"), JS_RUNTIME_EXTENSIONS.items())
def test_repository_language_detection_includes_js_ts_module_extensions(
    suffix: str,
    language: str,
) -> None:
    detected = detect_language(Path(f"module{suffix}"))

    assert detected == language
    assert is_analysis_language(detected)


@pytest.mark.parametrize(("suffix", "runtime_name"), JS_RUNTIME_NAMES.items())
def test_ecmascript_runtime_uses_module_suffix_over_stale_language(
    suffix: str,
    runtime_name: str,
) -> None:
    runtime = ecmascript._runtime_for(Path(f"module{suffix}"), "JavaScript")

    assert runtime.language_name == runtime_name


def test_js_ts_treesitter_extracts_tsx_component_like_arrow(tmp_path: Path) -> None:
    path = tmp_path / "view.tsx"
    path.write_text(
        "export const View = (props: Props): JSX.Element => <section>{props.title}</section>\n",
        encoding="utf-8",
    )
    registry = default_language_registry()
    adapter = registry.adapter_for_language("TSX")

    assert adapter is not None
    analysis = adapter.extract_analysis(LanguageAnalysisContext(path, "view.tsx", "source", "TSX"))

    assert analysis.functions[0].symbol == "View"
    assert analysis.functions[0].parameter_count == 1
    assert analysis.signatures[0].return_type == "JSX.Element"
    assert analysis.signatures[0].parameters == ["Props"]


def test_default_registry_extracts_each_adapter_language(tmp_path: Path) -> None:
    cases = [
        ("Python", "mod.py", "def run(value: str) -> str:\n    return value\n", "run"),
        (
            "JavaScript",
            "mod.js",
            "export function load(path) { return path }\n",
            "load",
        ),
        (
            "TypeScript",
            "mod.ts",
            "export function load(path: string): Config { return parse(path) }\n",
            "load",
        ),
        (
            "TSX",
            "mod.tsx",
            "export const View = (props: Props): JSX.Element => <section />\n",
            "View",
        ),
    ]
    registry = default_language_registry()

    for language, filename, source, symbol in cases:
        path = tmp_path / filename
        path.write_text(source, encoding="utf-8")
        adapter = registry.adapter_for_language(language)

        assert adapter is not None
        analysis = adapter.extract_analysis(
            LanguageAnalysisContext(path, filename, "source", language)
        )

        assert analysis.functions[0].symbol == symbol
        assert analysis.signatures[0].symbol == symbol


def test_js_ts_signatures_include_tree_sitter_control_and_call_shapes(tmp_path: Path) -> None:
    path = tmp_path / "service.ts"
    path.write_text(
        """
function save(path: PathLike, text: string): string {
  if (!path) return text;
  path.parent.mkdir({ recursive: true });
  return write(path, text);
}
""".lstrip(),
        encoding="utf-8",
    )
    adapter = default_language_registry().adapter_for_language("TypeScript")

    assert adapter is not None
    signature = adapter.extract_analysis(
        LanguageAnalysisContext(path, "service.ts", "source", "TypeScript")
    ).signatures[0]

    assert signature.statement_sequence == [
        "IF",
        "CALL:ARG0.parent.mkdir(args=OBJECT;kwargs=)",
        "RETURN:ARG0,ARG1",
    ]
    assert signature.call_tokens == (
        "ARG0.parent.mkdir(args=OBJECT;kwargs=)",
        "write(args=ARG0,ARG1;kwargs=)",
    )
    assert signature.call_fingerprints == ()
    assert signature.parameter_use_vectors == {}
    assert not signature.local_dataflow_graph.edges
    provider = relation_detail_provider(adapter)
    assert provider is not None
    detail = provider.hydrate_relation_detail(
        _relation_detail_request(path, "service.ts", "TypeScript", "save", "sig_service")
    )
    assert [call.token for call in detail.call_fingerprints] == [
        "ARG0.parent.mkdir(args=OBJECT;kwargs=)",
        "write(args=ARG0,ARG1;kwargs=)",
    ]
    parameter_features = dict(detail.parameter_features)
    assert "receiver_of_calls:parent.mkdir" in parameter_features["ARG0"]
    assert "passed_as_argument_to:write.arg1" in parameter_features["ARG1"]
    assert detail.graph_features
    assert signature.control_context_vector == ["BRANCH"]
    assert signature.body_shape
    assert signature.body_shape_hash.startswith("sha256:")
    assert signature.body_tree_node_count > 0


@pytest.mark.parametrize(
    ("left_symbol", "right_symbol", "expected_same"),
    [
        ("trimLeft", "trimRight", True),
        ("localLeft", "localRight", True),
        ("parseValue", "serializeValue", False),
    ],
)
def test_js_ts_body_shape_normalizes_roles_but_preserves_operations(
    left_symbol: str,
    right_symbol: str,
    expected_same: bool,
) -> None:
    signatures = _fixture_analysis("js_ts_body_shapes.ts").signatures
    left = _signature_by_symbol(signatures, left_symbol)
    right = _signature_by_symbol(signatures, right_symbol)

    assert left.body_shape
    assert right.body_shape
    assert left.body_tree_node_count > 0
    assert right.body_tree_node_count > 0
    assert (left.body_shape_hash == right.body_shape_hash) is expected_same


def test_js_ts_declaration_signature_has_no_body_shape_hash() -> None:
    analysis = _fixture_analysis(
        "js_ts_declaration_surface.d.ts",
        language="TypeScript",
    )

    assert analysis.functions == ()
    assert analysis.signatures[0].symbol == "load"
    assert analysis.signatures[0].body_shape == ""
    assert analysis.signatures[0].body_shape_hash == ""
    assert analysis.signatures[0].body_tree_node_count == 0
    assert FunctionSemanticRole.ABSTRACT_OR_INTERFACE_STUB in analysis.signatures[0].semantic_roles


def test_js_ts_small_forwarder_is_api_surface() -> None:
    signatures = _fixture_analysis("js_ts_forwarders.ts").signatures

    assert all(
        FunctionSemanticRole.ADAPTER_FORWARDER in signature.semantic_roles
        for signature in signatures
    )
    assert all(
        FunctionSemanticRole.PUBLIC_API_MIRROR in signature.semantic_roles
        for signature in signatures
    )


def test_js_ts_path_roles_mark_generated_and_test_surfaces() -> None:
    generated = _fixture_analysis(
        "js_ts_path_role_surface.ts",
        relative_path=".yarn/releases/yarn-4.12.0.cjs",
        role="vendor",
    ).signatures[0]
    test = _fixture_analysis(
        "js_ts_path_role_surface.ts",
        relative_path="packages/app/foo.test.ts",
        role="test",
    ).signatures[0]

    assert FunctionSemanticRole.GENERATED_OR_CYTHON_BOUNDARY in generated.semantic_roles
    assert FunctionSemanticRole.TEST_CODE in test.semantic_roles


@pytest.mark.parametrize(
    ("symbol", "expected_roles"),
    (
        (
            "load",
            {
                FunctionSemanticRole.ABSTRACT_OR_INTERFACE_STUB,
                FunctionSemanticRole.DECLARATION_BOUNDARY,
            },
        ),
        (
            "run",
            {
                FunctionSemanticRole.ABSTRACT_OR_INTERFACE_STUB,
                FunctionSemanticRole.DECLARATION_BOUNDARY,
            },
        ),
        (
            "value",
            {
                FunctionSemanticRole.PROPERTY_ACCESSOR,
            },
        ),
        (
            "constructor",
            {
                FunctionSemanticRole.CONSTRUCTOR,
            },
        ),
        (
            "execute",
            {
                FunctionSemanticRole.OVERLOAD_SIGNATURE,
                FunctionSemanticRole.ABSTRACT_OR_INTERFACE_STUB,
                FunctionSemanticRole.DECLARATION_BOUNDARY,
            },
        ),
        (
            "query",
            {
                FunctionSemanticRole.ADAPTER_FORWARDER,
                FunctionSemanticRole.PUBLIC_API_MIRROR,
            },
        ),
        (
            "useRecordState",
            {
                FunctionSemanticRole.FRAMEWORK_HOOK,
            },
        ),
        (
            "RecordPanel",
            {
                FunctionSemanticRole.FRAMEWORK_RENDER_SURFACE,
            },
        ),
        (
            "InlinePanel",
            {
                FunctionSemanticRole.FRAMEWORK_RENDER_SURFACE,
            },
        ),
        (
            "mapStateToProps",
            {
                FunctionSemanticRole.FRAMEWORK_CONNECTOR,
            },
        ),
        (
            "isListNode",
            {
                FunctionSemanticRole.PREDICATE_BOUNDARY,
            },
        ),
        (
            "hasUuid",
            {
                FunctionSemanticRole.IMPLEMENTATION_CONTRACT_METHOD,
                FunctionSemanticRole.PREDICATE_BOUNDARY,
            },
        ),
        (
            "supportsShare",
            {
                FunctionSemanticRole.IMPLEMENTATION_CONTRACT_METHOD,
                FunctionSemanticRole.PREDICATE_BOUNDARY,
            },
        ),
        (
            "initSynchronizer",
            {
                FunctionSemanticRole.IMPLEMENTATION_CONTRACT_METHOD,
            },
        ),
        (
            "runtime",
            {
                FunctionSemanticRole.COMMAND_OR_REGISTRY_SURFACE,
            },
        ),
        (
            "registerExportCommand",
            {
                FunctionSemanticRole.COMMAND_OR_REGISTRY_SURFACE,
            },
        ),
    ),
)
def test_js_ts_semantic_roles_for_declarations_api_and_framework_surfaces(
    symbol: str,
    expected_roles: set[FunctionSemanticRole],
) -> None:
    signatures = _fixture_analysis(
        "js_ts_semantic_roles.tsx",
        language="TSX",
    ).signatures
    matching = [signature for signature in signatures if signature.symbol == symbol]

    assert matching
    assert any(expected_roles <= set(signature.semantic_roles) for signature in matching)


def test_js_ts_declaration_file_marks_declaration_boundary() -> None:
    signature = _fixture_analysis(
        "js_ts_declaration_surface.d.ts",
        language="TypeScript",
    ).signatures[0]

    assert FunctionSemanticRole.DECLARATION_BOUNDARY in signature.semantic_roles
    assert FunctionSemanticRole.ABSTRACT_OR_INTERFACE_STUB in signature.semantic_roles


def test_js_ts_run_cache_reuses_source_and_function_parse(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    path = tmp_path / "service.ts"
    path.write_text(
        "export function load(path: string): Config { return parse(path) }\n",
        encoding="utf-8",
    )
    adapter = default_language_registry().adapter_for_language("TypeScript")
    cache = LanguageRunCache()
    context = LanguageAnalysisContext(
        path=path,
        relative_path="service.ts",
        role="source",
        language="TypeScript",
        content_hash="content-v1",
        run_cache=cache,
    )
    read_count = 0
    parse_count = 0
    read_bytes = Path.read_bytes
    parse_functions = ecmascript._parse_functions

    def counted_read_bytes(self: Path) -> bytes:
        nonlocal read_count
        read_count += 1
        return read_bytes(self)

    def counted_parse_functions(
        context: LanguageAnalysisContext,
        source: bytes,
    ) -> list[FunctionIR]:
        nonlocal parse_count
        parse_count += 1
        return parse_functions(context, source)

    monkeypatch.setattr(Path, "read_bytes", counted_read_bytes)
    monkeypatch.setattr(ecmascript, "_parse_functions", counted_parse_functions)

    assert adapter is not None
    analysis = adapter.extract_analysis(context)
    assert analysis.functions[0].symbol == "load"
    assert analysis.signatures[0].symbol == "load"
    assert read_count == 1
    assert parse_count == 1


def test_persistent_signature_cache_preserves_statement_sequences(tmp_path: Path) -> None:
    path = tmp_path / "service.ts"
    path.write_text(
        """
function save(path: PathLike, text: string): string {
  if (!path) return text;
  return write(path, text);
}
""".lstrip(),
        encoding="utf-8",
    )
    registry = default_language_registry()
    file_record = _file_record("service.ts", content_hash="content-v1")
    context = LanguageAnalysisContext(
        path=path,
        relative_path="service.ts",
        role="source",
        language="TypeScript",
        content_hash=file_record.content_hash,
    )

    first_cache = persistent_cache(tmp_path / ".cache", enabled=True)
    try:
        first = analyze_language_file(
            context,
            file_record,
            registry,
            AnalysisCacheContext(
                persistent=first_cache,
                file_analysis_enabled=True,
                relation_pair_enabled=False,
                language=LanguageRunCache(),
            ),
        )
    finally:
        first_cache.close()

    second_cache = persistent_cache(tmp_path / ".cache", enabled=True)
    try:
        second = analyze_language_file(
            context,
            file_record,
            registry,
            AnalysisCacheContext(
                persistent=second_cache,
                file_analysis_enabled=True,
                relation_pair_enabled=False,
                language=LanguageRunCache(),
            ),
        )
    finally:
        second_cache.close()

    assert (
        first.signatures[0].core.statement_sequence == second.signatures[0].core.statement_sequence
    )
    assert second.signatures[0].core.statement_sequence == ("IF", "RETURN:ARG0,ARG1")
    assert first.signatures[0].core.body_shape_hash == second.signatures[0].core.body_shape_hash
    assert second.signatures[0].core.body_shape_hash.startswith("sha256:")


def test_signature_cache_payload_omits_body_tree(tmp_path: Path) -> None:
    path = tmp_path / "service.py"
    path.write_text(
        "def save(value: str) -> str:\n    return value.strip()\n",
        encoding="utf-8",
    )
    adapter = default_language_registry().adapter_for_language("Python")

    assert adapter is not None
    records = adapter.extract_analysis(
        LanguageAnalysisContext(path, "service.py", "source", "Python")
    ).signatures
    assert records[0].body_tree is None
    assert records[0].body_shape == ""
    assert records[0].body_shape_hash.startswith("shape32:")
    assert records[0].body_tree_node_count > 0

    analyses = signature_analyses_from_records(records)
    core_payload = signature_core_cache_payload(analyses)
    features_payload = signature_features_cache_payload(analyses)
    output_payload = signature_output_cache_payload(analyses)
    restored = signature_analyses_from_cache_values(
        core_payload,
        features_payload,
        output_payload,
    )

    assert isinstance(core_payload[0], SignatureCore)
    assert output_payload[0].body_shape == ""
    assert restored is not None
    assert not hasattr(restored[0].core, "body_tree")
    assert restored[0].core.body_tree_node_count == records[0].body_tree_node_count
    assert restored[0].core.statement_sequence == tuple(records[0].statement_sequence)
    assert records[0].call_fingerprints == ()
    assert restored[0].core.call_tokens == records[0].call_tokens
    assert restored[0].features.graph_features == frozenset()

    assert isinstance(adapter, PythonAstAdapter)
    relation_detail = adapter.hydrate_relation_detail(
        _relation_detail_request(path, "service.py", "Python", "save", "sig_1")
    )
    assert relation_detail.graph_features


def test_python_relation_detail_reuses_extraction_function_nodes(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    path = tmp_path / "service.py"
    path.write_text(
        "def save(value: str) -> str:\n    cleaned = value.strip()\n    return cleaned\n",
        encoding="utf-8",
    )
    adapter = default_language_registry().adapter_for_language("Python")
    assert isinstance(adapter, PythonAstAdapter)

    request = _relation_detail_request(path, "service.py", "Python", "save", "sig_1")

    def fail_function_node_index(_tree: object) -> object:
        raise AssertionError("relation hydration should reuse extraction function nodes")

    monkeypatch.setattr(
        "codeseam.adapters.languages.python.adapter.function_node_index",
        fail_function_node_index,
    )

    relation_detail = adapter.hydrate_relation_detail(request)

    assert relation_detail.graph_features


def test_python_relation_detail_warm_cache_uses_function_slice(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    path = tmp_path / "service.py"
    path.write_text(
        "def save(value: str) -> str:\n    cleaned = value.strip()\n    return cleaned\n",
        encoding="utf-8",
    )
    adapter = default_language_registry().adapter_for_language("Python")
    assert isinstance(adapter, PythonAstAdapter)

    extraction_request = _relation_detail_request(path, "service.py", "Python", "save", "sig_1")
    warm_context = LanguageAnalysisContext(
        path,
        "service.py",
        "source",
        "Python",
        run_cache=LanguageRunCache(),
    )
    request = RelationDetailRequest(
        context=warm_context,
        signature=extraction_request.signature,
        function=extraction_request.function,
    )

    def fail_full_file_parse(_path: object) -> object:
        raise AssertionError("warm relation hydration should not parse the full file")

    def fail_function_node_index(_tree: object) -> object:
        raise AssertionError("warm relation hydration should not index a full-file AST")

    monkeypatch.setattr(
        "codeseam.adapters.languages.python.adapter.parse_python",
        fail_full_file_parse,
    )
    monkeypatch.setattr(
        "codeseam.adapters.languages.python.adapter.function_node_index",
        fail_function_node_index,
    )

    relation_detail = adapter.hydrate_relation_detail(request)

    assert relation_detail.graph_features


def test_ecmascript_base_extraction_keeps_relation_detail_lazy() -> None:
    analysis = _fixture_analysis("js_ts_relation_detail.ts")
    record = next(item for item in analysis.signatures if item.symbol == "parseEncoded")
    restored = signature_analyses_from_records([record])[0]

    assert record.call_tokens
    assert record.call_fingerprints == ()
    assert restored.features.graph_features == frozenset()
    assert restored.features.literal_shapes == frozenset()
    assert restored.features.receiver_shapes == frozenset()
    assert restored.features.parameter_features == ()
    assert restored.features.statement_arg_reads == ()


def test_ecmascript_relation_detail_hydrates_function_slice() -> None:
    detail = _relation_detail_provider_for("TypeScript").hydrate_relation_detail(
        _fixture_relation_detail_request(
            "js_ts_relation_detail.ts",
            "parseEncoded",
            "sig_ts_detail",
        )
    )

    assert detail.signature_id == "sig_ts_detail"
    assert detail.call_fingerprints
    assert detail.graph_features
    assert detail.literal_shapes
    assert detail.receiver_shapes
    assert detail.parameter_features
    assert detail.normalization_transform_tokens
    assert detail.statement_arg_reads


def test_ecmascript_relation_detail_hydrates_method_slice() -> None:
    detail = _relation_detail_provider_for("TypeScript").hydrate_relation_detail(
        _fixture_relation_detail_request("js_ts_relation_detail.ts", "save", "sig_ts_method_detail")
    )

    assert detail.signature_id == "sig_ts_method_detail"
    assert detail.graph_features
    assert detail.parameter_features
    assert detail.statement_arg_reads


def _relation_detail_provider_for(language: str) -> RelationDetailProvider:
    adapter = default_language_registry().adapter_for_language(language)
    provider = relation_detail_provider(adapter)

    assert provider is not None
    return provider


def _fixture_relation_detail_request(
    fixture_name: str,
    symbol: str,
    signature_id: str,
    *,
    language: str = "TypeScript",
) -> RelationDetailRequest:
    path = LANGUAGE_FIXTURES / fixture_name
    return _relation_detail_request(path, fixture_name, language, symbol, signature_id)


def _relation_detail_request(
    path: Path,
    relative_path: str,
    language: str,
    symbol: str,
    signature_id: str,
) -> RelationDetailRequest:
    adapter = default_language_registry().adapter_for_language(language)
    assert adapter is not None
    context = LanguageAnalysisContext(
        path,
        relative_path,
        "source",
        language,
        run_cache=LanguageRunCache(),
    )
    analysis = adapter.extract_analysis(context)
    record = _signature_by_symbol(analysis.signatures, symbol)
    record.signature_id = signature_id
    return RelationDetailRequest(
        context=context,
        signature=signature_analyses_from_records([record])[0],
        function=next(function for function in analysis.functions if function.symbol == symbol),
    )


def _fixture_analysis(
    fixture_name: str,
    *,
    relative_path: str | None = None,
    role: str = "source",
    language: str = "TypeScript",
) -> LanguageAdapterAnalysis:
    path = LANGUAGE_FIXTURES / fixture_name
    adapter = default_language_registry().adapter_for_language(language)

    assert adapter is not None
    return adapter.extract_analysis(
        LanguageAnalysisContext(path, relative_path or fixture_name, role, language)
    )


def _signature_by_symbol(
    signatures: tuple[SignatureRecord, ...],
    symbol: str,
) -> SignatureRecord:
    return next(signature for signature in signatures if signature.symbol == symbol)


def _typescript_project_facts(items: tuple[RepositoryAdapterFact, ...]) -> TypeScriptProjectFacts:
    facts = next(
        item.facts for item in items if getattr(item, "adapter_id", "") == ecmascript.ADAPTER_ID
    )
    assert isinstance(facts, TypeScriptProjectFacts)
    return facts


class _RepoFactsAdapter(StaticLanguageSupport):
    adapter_id = AdapterId.UNKNOWN
    languages = frozenset({"Fake"})
    capabilities = AdapterCapabilities(syntax_frontend="fake_parser", repo_facts=True)

    def extract_analysis(self, context: LanguageAnalysisContext) -> LanguageAdapterAnalysis:
        del context
        return LanguageAdapterAnalysis(functions=(), signatures=())

    def extract_repo_facts(self, facts: object) -> object:
        return {"selected_files": getattr(facts, "selected_file_count", 0)}
