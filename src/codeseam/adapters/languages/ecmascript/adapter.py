from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import tree_sitter_javascript as tsjavascript
import tree_sitter_typescript as tstypescript
from tree_sitter import Language, Node

from codeseam.adapters.languages.base import (
    LanguageAdapterAnalysis,
    LanguageAnalysisContext,
    StaticLanguageSupport,
)
from codeseam.adapters.languages.capabilities import AdapterCapabilities
from codeseam.adapters.languages.ecmascript.compiler_facts import (
    TypeScriptProjectFacts,
    extract_typescript_project_facts,
)
from codeseam.adapters.languages.ecmascript.duplicate_blocks import (
    ecmascript_intra_function_duplicate_blocks,
)
from codeseam.adapters.languages.ecmascript.features import operation_features
from codeseam.adapters.languages.ecmascript.manifests import ECMASCRIPT_MANIFEST_MATCHERS
from codeseam.adapters.languages.ecmascript.runtime import (
    TreeSitterRuntime,
    iter_named_nodes,
    node_text,
)
from codeseam.adapters.languages.ecmascript.semantic_roles import (
    FunctionRoleContext,
    classify_function_roles,
)
from codeseam.adapters.languages.ecmascript.syntax_kinds import (
    BODY_CALLABLE_TYPES,
    BRANCH_TYPES,
    CALLABLE_TYPES,
    JSX_TYPES,
    LOOP_TYPES,
    TSX_SUFFIXES,
    TYPESCRIPT_SUFFIXES,
)
from codeseam.adapters.languages.relation_detail import RelationDetailRequest
from codeseam.analysis import (
    AdapterId,
    CallsitePattern,
    EvidenceKind,
    FunctionIR,
    FunctionRecord,
    LanguageFamily,
    ParamIR,
    RepositoryFacts,
    SignatureAnalysisFeatures,
    SignatureRecord,
    callsite_evidence_kinds,
    is_callable_return,
    signature_shape,
)
from codeseam.platform import normalize_identifier

JS_TS_LANGUAGES = frozenset({"TypeScript", "TSX", "JavaScript", "JSX"})
ADAPTER_ID = AdapterId.TREESITTER_ECMASCRIPT_TYPESCRIPT
LANGUAGE_FAMILY = LanguageFamily.ECMASCRIPT_TYPESCRIPT
HOOK_PREFIX = "use"
MIN_HOOK_NAME_LENGTH = len(HOOK_PREFIX) + 1
UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class _FunctionParseContext:
    file_path: str
    language: str
    repository_role: str
    overload_keys: frozenset[tuple[str, str]]


class ECMAScriptTypeScriptTreeSitterAdapter(StaticLanguageSupport):
    adapter_id = ADAPTER_ID
    languages = JS_TS_LANGUAGES
    manifest_matchers = ECMASCRIPT_MANIFEST_MATCHERS
    capabilities = AdapterCapabilities(
        syntax_frontend="tree_sitter",
        relation_detail=True,
        repo_facts=True,
    )

    def extract_analysis(self, context: LanguageAnalysisContext) -> LanguageAdapterAnalysis:
        source = _source_bytes(context)
        functions = _functions(context, source)
        signature_records = [_signature_record(function, context.role) for function in functions]
        lines = source.decode("utf-8", errors="replace").splitlines()
        _attach_callsite_evidence(signature_records, lines, context.relative_path)
        return LanguageAdapterAnalysis(
            functions=tuple(
                _function_record(function, context.role)
                for function in functions
                if function.has_body
            ),
            signatures=tuple(signature_records),
        )

    def hydrate_relation_detail(
        self,
        request: RelationDetailRequest,
    ) -> SignatureAnalysisFeatures:
        function = _request_function(request)
        if function is None:
            return SignatureAnalysisFeatures(signature_id=request.signature.core.signature_id)
        return _relation_detail_from_function(function, request.signature.core.signature_id)

    def extract_repo_facts(self, facts: RepositoryFacts) -> TypeScriptProjectFacts:
        return extract_typescript_project_facts(facts)


def _functions(
    context: LanguageAnalysisContext,
    source: bytes | None = None,
) -> list[FunctionIR]:
    source = source if source is not None else _source_bytes(context)
    if context.run_cache is not None:
        return context.run_cache.functions(
            context,
            lambda: _parse_functions(context, source),
        )
    return _parse_functions(context, source)


def _parse_functions(context: LanguageAnalysisContext, source: bytes) -> list[FunctionIR]:
    runtime = _runtime_for(context.path, context.language)
    root = runtime.parse(source).root_node
    callable_nodes = [node for node in iter_named_nodes(root) if node.type in CALLABLE_TYPES]
    overload_keys = _overload_signature_keys(source, callable_nodes)
    parse_context = _FunctionParseContext(
        file_path=context.relative_path,
        language=context.language,
        repository_role=context.role,
        overload_keys=overload_keys,
    )
    nodes = [
        _function_ir(
            source,
            node,
            parse_context,
        )
        for node in callable_nodes
    ]
    return sorted((node for node in nodes if node is not None), key=lambda item: item.start_line)


def _request_function(request: RelationDetailRequest) -> FunctionIR | None:
    core = request.signature.core
    return next(
        (
            function
            for function in _functions(request.context)
            if function.name == core.symbol and function.start_line == core.start_line
        ),
        None,
    )


def _relation_detail_from_function(
    function: FunctionIR,
    signature_id: str,
) -> SignatureAnalysisFeatures:
    return _relation_detail_from_source(function.source_text, signature_id)


def _relation_detail_from_source(source: str, signature_id: str) -> SignatureAnalysisFeatures:
    candidate = _relation_detail_callable(source.encode("utf-8", errors="replace"))
    if candidate is None:
        return SignatureAnalysisFeatures(signature_id=signature_id)
    source_bytes, node = candidate
    body_node = node.child_by_field_name("body")
    params = tuple(_params(source_bytes, node.child_by_field_name("parameters")))
    features = operation_features(
        source_bytes,
        body_node,
        params,
        include_relation_detail=True,
    )
    compact = features.compact
    return SignatureAnalysisFeatures(
        signature_id=signature_id,
        parameter_default_roles=compact.parameter_default_roles,
        graph_features=compact.graph_features,
        literal_shapes=compact.literal_shapes,
        receiver_shapes=compact.receiver_shapes,
        parameter_features=compact.parameter_features,
        normalization_transform_tokens=frozenset(compact.normalization_transform_tokens),
        statement_arg_reads=compact.statement_arg_reads,
        call_fingerprints=features.flow.call_fingerprints,
    )


def _relation_detail_callable(source: bytes) -> tuple[bytes, Node] | None:
    stripped = source.strip().rstrip(b";")
    variants = (
        source,
        b"class __CodeseamRelationDetail {\n" + source + b"\n}",
        b"const __codeseamRelationDetail = " + stripped + b";",
    )
    for candidate in variants:
        node = _first_body_callable(candidate)
        if node is not None:
            return candidate, node
    return None


def _first_body_callable(source: bytes) -> Node | None:
    root = _runtime("tsx").parse(source).root_node
    return next(
        (
            node
            for node in iter_named_nodes(root)
            if node.type in BODY_CALLABLE_TYPES and node.child_by_field_name("body") is not None
        ),
        None,
    )


def _runtime_for(path: Path, language: str) -> TreeSitterRuntime:
    suffix = path.suffix.lower()
    if suffix in TSX_SUFFIXES or language == "TSX":
        return _runtime("tsx")
    if suffix in TYPESCRIPT_SUFFIXES or language == "TypeScript":
        return _runtime("typescript")
    return _runtime("javascript")


@lru_cache(maxsize=3)
def _runtime(language_name: str) -> TreeSitterRuntime:
    """Reuse one parser for each ECMAScript grammar variant."""

    if language_name == "tsx":
        return TreeSitterRuntime.from_language(
            "tsx",
            Language(tstypescript.language_tsx()),
        )
    if language_name == "typescript":
        return TreeSitterRuntime.from_language(
            "typescript",
            Language(tstypescript.language_typescript()),
        )
    return TreeSitterRuntime.from_language(
        "javascript",
        Language(tsjavascript.language()),
    )


def _source_bytes(context: LanguageAnalysisContext) -> bytes:
    if context.run_cache is not None:
        return context.run_cache.source_bytes(context)
    return context.path.read_bytes()


def _function_ir(
    source: bytes,
    node: Node,
    context: _FunctionParseContext,
) -> FunctionIR | None:
    body_node = node.child_by_field_name("body")
    symbol = _symbol(source, node)
    if not symbol:
        return None

    raw_signature = _raw_signature(source, node, body_node)
    body_text = node_text(source, body_node) or ""
    source_text = node_text(source, node) or ""
    scope_node = body_node or node
    params = tuple(_params(source, node.child_by_field_name("parameters")))
    body_line_count = max(1, node.end_point[0] - node.start_point[0] + 1)
    semantic_roles = classify_function_roles(
        FunctionRoleContext(
            file_path=context.file_path,
            repository_role=context.repository_role,
            syntax_kind=node.type,
            symbol=symbol,
            raw_signature=raw_signature,
            body_text=body_text,
            body_line_count=body_line_count,
            is_overload_signature=(
                body_node is None and _callable_key(source, node, symbol) in context.overload_keys
            ),
            has_jsx_body=_contains_node_type(body_node, JSX_TYPES),
            has_hook_call=_has_hook_call(source, body_node),
        )
    )
    return FunctionIR(
        language=context.language.lower(),
        language_family=LANGUAGE_FAMILY,
        file=context.file_path,
        name=symbol,
        container=_container(source, node),
        kind=_function_kind(node),
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        is_async=bool(re.search(r"\basync\b", raw_signature)),
        is_exported_or_public=_is_exported(node) or not symbol.startswith("_"),
        params=params,
        return_annotation=(
            _clean_optional_text(
                node_text(source, node.child_by_field_name("return_type")),
                strip_type_marker,
            )
            or UNKNOWN
        ),
        declared_generics=tuple(
            _generics(node_text(source, node.child_by_field_name("type_parameters")))
        ),
        raw_signature=raw_signature,
        source_text=source_text,
        body_text=body_text if node.type in BODY_CALLABLE_TYPES else "",
        body_line_count=body_line_count,
        branch_count=_count_nodes(scope_node, BRANCH_TYPES),
        loop_count=_count_nodes(scope_node, LOOP_TYPES),
        return_count=_count_nodes(scope_node, frozenset({"return_statement"})),
        max_nesting=_brace_nesting(body_text or source_text),
        adapter=ADAPTER_ID,
        extraction_confidence="high",
        caveats=(),
        features=operation_features(source, body_node, params),
        syntax_kind=node.type,
        semantic_roles=semantic_roles.roles,
        semantic_role_reasons=semantic_roles.reasons,
        intra_function_duplicate_blocks=ecmascript_intra_function_duplicate_blocks(
            source,
            body_node,
            params,
        ),
    )


def _symbol(source: bytes, node: Node) -> str | None:
    if name := _clean_optional_text(
        node_text(source, node.child_by_field_name("name")),
        clean_symbol_text,
    ):
        return name
    parent = node.parent
    if parent is None:
        return None
    if parent.type == "variable_declarator":
        return _clean_optional_text(
            node_text(source, parent.child_by_field_name("name")),
            clean_symbol_text,
        )
    if parent.type == "pair":
        return _clean_optional_text(
            node_text(source, parent.child_by_field_name("key")),
            clean_symbol_text,
        )
    if parent.type == "assignment_expression":
        return _clean_optional_text(
            node_text(source, parent.child_by_field_name("left")),
            clean_symbol_text,
        )
    return None


def _container(source: bytes, node: Node) -> str | None:
    current = node.parent
    while current is not None:
        if current.type == "class_declaration":
            return node_text(source, current.child_by_field_name("name"))
        current = current.parent
    return None


def _callable_key(source: bytes, node: Node, symbol: str | None = None) -> tuple[str, str]:
    return (_container(source, node) or "", symbol or _symbol(source, node) or "")


def _overload_signature_keys(
    source: bytes,
    nodes: list[Node],
) -> frozenset[tuple[str, str]]:
    body_keys = {
        _callable_key(source, node)
        for node in nodes
        if node.child_by_field_name("body") is not None
    }
    declaration_keys = {
        _callable_key(source, node) for node in nodes if node.child_by_field_name("body") is None
    }
    return frozenset(key for key in declaration_keys if key in body_keys and key[1])


def _is_exported(node: Node) -> bool:
    current = node.parent
    while current is not None:
        if current.type == "export_statement":
            return True
        current = current.parent
    return False


def _function_kind(node: Node) -> str:
    if node.type in {"method_definition", "method_signature", "abstract_method_signature"}:
        return "method"
    if node.type == "arrow_function":
        return "arrow_function"
    if node.type == "function_expression":
        return "function_expression"
    return "function"


def _params(source: bytes, params_node: Node | None) -> list[ParamIR]:
    if params_node is None:
        return []
    return [_param(source, child) for child in params_node.named_children]


def _param(source: bytes, node: Node) -> ParamIR:
    if node.type in {"required_parameter", "optional_parameter"}:
        return ParamIR(
            annotation=_clean_optional_text(
                node_text(source, node.child_by_field_name("type")),
                strip_type_marker,
            ),
            name=node_text(source, node.child_by_field_name("pattern")),
            has_default=node.type == "optional_parameter",
        )
    if node.type == "assignment_pattern":
        left = node.child_by_field_name("left")
        left_type = left.child_by_field_name("type") if left is not None else None
        return ParamIR(
            annotation=_clean_optional_text(node_text(source, left_type), strip_type_marker),
            name=node_text(source, left),
            has_default=True,
        )
    return ParamIR(annotation=None, name=node_text(source, node))


def clean_symbol_text(value: str) -> str:
    return value.strip("'\"")


def strip_type_marker(value: str) -> str:
    return value[1:].strip() if value.startswith(":") else value


def _clean_optional_text(
    text: str | None,
    transform: Callable[[str], str],
) -> str | None:
    if text is None:
        return None
    cleaned = transform(text.strip())
    return cleaned or None


def _generics(text: str | None) -> list[str]:
    if not text:
        return []
    inner = text.strip().removeprefix("<").removesuffix(">")
    return [item.strip().split()[0] for item in inner.split(",") if item.strip()]


def _raw_signature(source: bytes, node: Node, body_node: Node | None) -> str:
    end_byte = body_node.start_byte if body_node is not None else node.end_byte
    return source[node.start_byte : end_byte].decode("utf-8", errors="replace").strip().rstrip(";")


def _count_nodes(node: Node, types: frozenset[str]) -> int:
    return sum(1 for item in iter_named_nodes(node) if item.type in types)


def _contains_node_type(node: Node | None, types: frozenset[str]) -> bool:
    return node is not None and any(item.type in types for item in iter_named_nodes(node))


def _has_hook_call(source: bytes, node: Node | None) -> bool:
    if node is None:
        return False
    return any(
        _is_hook_name(_call_name(source, item))
        for item in iter_named_nodes(node)
        if item.type == "call_expression"
    )


def _is_hook_name(name: str) -> bool:
    return (
        name.startswith(HOOK_PREFIX)
        and len(name) >= MIN_HOOK_NAME_LENGTH
        and name[len(HOOK_PREFIX) : len(HOOK_PREFIX) + 1].isupper()
    )


def _call_name(source: bytes, call: Node) -> str:
    callee = call.child_by_field_name("function")
    if callee is None:
        return ""
    if callee.type == "identifier":
        return node_text(source, callee) or ""
    if callee.type == "member_expression":
        return node_text(source, callee.child_by_field_name("property")) or ""
    return ""


def _brace_nesting(source: str) -> int:
    depth = 0
    maximum = 0
    for char in source:
        if char == "{":
            depth += 1
            maximum = max(maximum, depth)
        elif char == "}":
            depth = max(0, depth - 1)
    return maximum


def _function_record(function: FunctionIR, role: str) -> FunctionRecord:
    return FunctionRecord(
        language=function.language,
        file=function.file,
        symbol=function.name,
        container=function.container,
        start_line=function.start_line,
        end_line=function.end_line,
        is_exported_or_public=function.is_exported_or_public,
        is_async=function.is_async,
        parameter_count=len(function.params),
        branch_count=function.branch_count,
        loop_count=function.loop_count,
        return_count=function.return_count,
        max_nesting=function.max_nesting,
        role=role,
        source=function.source_text,
        caveats=list(function.caveats),
        extraction_confidence=function.extraction_confidence,
    )


def _signature_record(function: FunctionIR, role: str) -> SignatureRecord:
    shape = signature_shape(function)
    features = function.features
    return SignatureRecord(
        language=function.language,
        language_family=function.language_family,
        adapter=function.adapter,
        file=function.file,
        symbol=function.name,
        normalized_symbol=normalize_identifier(function.name),
        container=function.container,
        start_line=function.start_line,
        end_line=function.end_line,
        role=role,
        type_source=shape.type_source,
        parameters=shape.parameters,
        return_type=shape.return_type,
        raw_signature=function.raw_signature,
        canonical_shape=shape.canonical_shape,
        shape_hash=shape.shape_hash,
        body_line_count=function.body_line_count,
        body_shape=features.compact.body_shape,
        body_shape_hash=features.compact.body_shape_hash,
        body_tree=None,
        body_tree_node_count=features.compact.body_tree_node_count,
        statement_sequence=list(features.compact.statement_sequence),
        call_tokens=features.compact.call_tokens,
        call_fingerprints=features.flow.call_fingerprints,
        parameter_use_vectors=dict(features.flow.parameter_use_vectors),
        parameter_default_roles=dict(features.compact.parameter_default_roles),
        local_dataflow_graph=features.flow.local_dataflow_graph,
        control_context_vector=list(features.compact.control_context_vector),
        caveats=[*function.caveats, *shape.caveats],
        semantic_roles=function.semantic_roles,
        semantic_role_reasons=function.semantic_role_reasons,
        intra_function_duplicate_blocks=function.intra_function_duplicate_blocks,
    )


def _attach_callsite_evidence(
    records: list[SignatureRecord],
    lines: list[str],
    file_path: str,
) -> None:
    factories = {record.symbol for record in records if is_callable_return(record.return_type)}
    if not factories:
        return
    patterns = _callsite_patterns(lines, factories, file_path)
    for record in records:
        symbol = record.symbol
        if symbol not in factories:
            continue
        symbol_patterns = patterns.get(symbol, [])
        record.is_callable_factory = True
        record.evidence_kinds = [
            EvidenceKind.CALLABLE_FACTORY,
            *callsite_evidence_kinds(symbol_patterns),
        ]
        record.callsite_patterns = tuple(symbol_patterns)


def _callsite_patterns(
    lines: list[str],
    factories: set[str],
    file_path: str,
) -> dict[str, list[CallsitePattern]]:
    patterns: dict[str, list[CallsitePattern]] = defaultdict(list)
    assigned: dict[str, tuple[str, int]] = {}
    uses: dict[str, int] = defaultdict(int)
    for line_no, line in enumerate(lines, 1):
        for symbol in factories:
            escaped = re.escape(symbol)
            if re.search(rf"\b{escaped}\s*\([^)]*\)\s*\(", line):
                _add(patterns, symbol, EvidenceKind.CALLSITE_IMMEDIATE, file_path, line_no)
            if re.search(rf"\.(?:map|filter)\s*\(\s*{escaped}\s*\(", line):
                _add(patterns, symbol, EvidenceKind.CALLSITE_PIPELINE, file_path, line_no)
            if re.search(rf"\b(?:map|filter|pipe)\s*\(\s*{escaped}\s*\(", line):
                _add(patterns, symbol, EvidenceKind.CALLSITE_PIPELINE, file_path, line_no)
            if re.search(rf"\b(?:register|add|use|route|on)\w*\s*\([^)]*{escaped}\s*\(", line):
                _add(patterns, symbol, EvidenceKind.CALLSITE_REGISTERED, file_path, line_no)
            if re.search(rf"\bcache(?:\.set|\[).*{escaped}\s*\(", line):
                _add(patterns, symbol, EvidenceKind.CALLSITE_CACHED, file_path, line_no)
            assignment_re = rf"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*{escaped}\s*\("
            if match := re.search(assignment_re, line):
                assigned[match.group(1)] = (symbol, line_no)
        for variable in assigned:
            if re.search(rf"\b{re.escape(variable)}\s*\(", line):
                uses[variable] += 1
    for variable, (symbol, line_no) in assigned.items():
        if uses[variable] > 1:
            _add(
                patterns,
                symbol,
                EvidenceKind.CALLSITE_STORED_REUSE,
                file_path,
                line_no,
                variable=variable,
            )
    return dict(patterns)


def _add(
    patterns: dict[str, list[CallsitePattern]],
    symbol: str,
    kind: str,
    file_path: str,
    line: int,
    **extra: object,
) -> None:
    item = CallsitePattern(
        kind=kind,
        symbol=symbol,
        file=file_path,
        line=line,
        variable=str(extra.get("variable", "")),
    )
    if item not in patterns[symbol]:
        patterns[symbol].append(item)


__all__ = [
    "JS_TS_LANGUAGES",
    "ECMAScriptTypeScriptTreeSitterAdapter",
]
