from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path
from textwrap import dedent
from typing import cast

from codeseam.adapters.languages.base import LanguageAdapterAnalysis
from codeseam.adapters.languages.python.analysis import (
    PythonAnalysis,
    PythonFunctionNode,
    parse_python,
)
from codeseam.adapters.languages.python.ast_utils import (
    ClassStackVisitor,
    unparse_ast,
)
from codeseam.adapters.languages.python.duplicate_blocks import (
    python_intra_function_duplicate_blocks,
)
from codeseam.adapters.languages.python.policy_constants import extract_policy_constants
from codeseam.adapters.languages.python.semantic_roles import classify_python_semantic_roles
from codeseam.adapters.languages.python.signature_features import operation_features
from codeseam.analysis import (
    AdapterId,
    CallsitePattern,
    EvidenceKind,
    FunctionRecord,
    LanguageFamily,
    SignatureAnalysisFeatures,
    SignatureRecord,
    SignatureTypeSource,
    callsite_evidence_kinds,
    canonical_shape,
    is_callable_return,
)
from codeseam.platform import normalize_identifier

UNKNOWN = "UNKNOWN"
LANGUAGE_FAMILY = LanguageFamily.PYTHON
PIPELINE_CALL_NAMES = {"filter", "map", "reduce", "sorted", "pipe", "then"}
REGISTER_CALL_TOKENS = ("add", "handler", "on", "register", "route", "use")


def extract_python_analysis(
    path: Path,
    file_path: str,
    role: str,
    language: str = "python",
    analysis: PythonAnalysis | None = None,
) -> LanguageAdapterAnalysis:
    parsed = analysis or parse_python(path)
    if parsed.syntax_error:
        return LanguageAdapterAnalysis(
            functions=(_function_parse_error(file_path, role, language, parsed.syntax_error),),
            signatures=(_parse_error(file_path, role, language, parsed.syntax_error),),
        )
    if parsed.tree is None:
        return LanguageAdapterAnalysis(functions=(), signatures=())
    visitor = _Visitor(file_path, role, language, parsed.lines)
    signatures = visitor.collect(parsed.tree)
    parsed.function_nodes = visitor.function_nodes
    _attach_callsite_evidence(parsed.tree, signatures)
    return LanguageAdapterAnalysis(
        functions=tuple(visitor.function_records),
        signatures=tuple(signatures),
        policy_constants=tuple(
            extract_policy_constants(
                language=language,
                relative_path=file_path,
                role=role,
                analysis=parsed,
            )
        ),
    )


def extract_python_relation_detail(
    node: ast.FunctionDef | ast.AsyncFunctionDef | None,
    signature_id: str,
) -> SignatureAnalysisFeatures:
    """Build relation-only Python features from the file parse owned by the adapter."""

    if node is None:
        return SignatureAnalysisFeatures(signature_id=signature_id)
    return _relation_detail_from_function(node, signature_id)


def extract_python_relation_detail_source(
    source: str,
    signature_id: str,
) -> SignatureAnalysisFeatures:
    """Build relation-only features from a cache-backed function source slice."""

    try:
        tree = ast.parse(dedent(source))
    except SyntaxError:
        return SignatureAnalysisFeatures(signature_id=signature_id)
    return extract_python_relation_detail(_top_level_function(tree), signature_id)


def _top_level_function(
    tree: ast.Module,
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    for node in tree.body:
        if type(node) in {ast.FunctionDef, ast.AsyncFunctionDef}:
            return cast(PythonFunctionNode, node)
    return None


def function_node_index(
    tree: ast.AST,
) -> dict[tuple[str, int], PythonFunctionNode]:
    index: dict[tuple[str, int], PythonFunctionNode] = {}
    for node in ast.walk(tree):
        if type(node) in {ast.FunctionDef, ast.AsyncFunctionDef}:
            function = cast(PythonFunctionNode, node)
            index[(function.name, function.lineno)] = function
    return index


def _relation_detail_from_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    signature_id: str,
) -> SignatureAnalysisFeatures:
    features = operation_features(node, include_relation_detail=True)
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
    )


class _Visitor(ClassStackVisitor[SignatureRecord]):
    def __init__(self, file_path: str, role: str, language: str, lines: list[str]) -> None:
        self.file_path = file_path
        self.role = role
        self.language = language
        self.lines = lines
        self.stack: list[str] = []
        self.records: list[SignatureRecord] = []
        self.function_records: list[FunctionRecord] = []
        self.function_nodes: dict[tuple[str, int], PythonFunctionNode] = {}

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node, is_async=True)

    def _visit_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        *,
        is_async: bool,
    ) -> None:
        params = [_annotation(arg.annotation) for arg in _args(node.args)]
        self.function_nodes[(node.name, node.lineno)] = node
        return_type = _annotation(node.returns)
        shape, shape_hash = canonical_shape(params, return_type)
        end_line = int(getattr(node, "end_lineno", node.lineno))
        body_line_count = end_line - node.lineno + 1
        source = "\n".join(self.lines[node.lineno - 1 : end_line])
        features = operation_features(node)
        self.function_records.append(
            FunctionRecord(
                language=self.language,
                file=self.file_path,
                symbol=node.name,
                container=".".join(self.stack) or None,
                start_line=node.lineno,
                end_line=end_line,
                is_exported_or_public=not node.name.startswith("_"),
                is_async=is_async,
                parameter_count=_parameter_count(node.args),
                branch_count=features.compact.branch_count,
                loop_count=features.compact.loop_count,
                return_count=features.compact.return_count,
                max_nesting=features.compact.max_nesting,
                role=self.role,
                source=source,
            )
        )
        tree_node_count = features.compact.body_tree_node_count
        semantic_roles = classify_python_semantic_roles(
            node,
            file_path=self.file_path,
            repository_role=self.role,
            body_line_count=body_line_count,
        )
        self.records.append(
            SignatureRecord(
                language=self.language,
                language_family=LANGUAGE_FAMILY,
                adapter=AdapterId.PYTHON_AST,
                file=self.file_path,
                symbol=node.name,
                normalized_symbol=normalize_identifier(node.name),
                container=".".join(self.stack) or None,
                start_line=node.lineno,
                end_line=end_line,
                role=self.role,
                type_source=SignatureTypeSource.DECLARED_SYNTAX,
                parameters=params,
                return_type=return_type,
                raw_signature=f"def {node.name}({','.join(params)}) -> {return_type}",
                canonical_shape=shape,
                shape_hash=shape_hash,
                body_line_count=body_line_count,
                body_shape="",
                body_shape_hash=features.compact.body_shape_hash,
                body_tree=None,
                body_tree_node_count=tree_node_count,
                statement_sequence=list(features.compact.statement_sequence),
                call_tokens=features.compact.call_tokens,
                call_fingerprints=features.flow.call_fingerprints,
                parameter_use_vectors=dict(features.flow.parameter_use_vectors),
                parameter_default_roles=dict(features.compact.parameter_default_roles),
                local_dataflow_graph=features.flow.local_dataflow_graph,
                graph_features=features.compact.graph_features,
                literal_shapes=features.compact.literal_shapes,
                receiver_shapes=features.compact.receiver_shapes,
                parameter_features=dict(features.compact.parameter_features),
                normalization_transform_tokens=features.compact.normalization_transform_tokens,
                statement_arg_reads=features.compact.statement_arg_reads,
                control_context_vector=list(features.compact.control_context_vector),
                caveats=[] if UNKNOWN not in [*params, return_type] else ["missing_annotations"],
                semantic_roles=semantic_roles.roles,
                semantic_role_reasons=semantic_roles.reasons,
                intra_function_duplicate_blocks=python_intra_function_duplicate_blocks(node),
            )
        )
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()


def _args(args: ast.arguments) -> list[ast.arg]:
    return [*args.posonlyargs, *args.args, *args.kwonlyargs]


def _parameter_count(args: ast.arguments) -> int:
    return (
        len(args.posonlyargs)
        + len(args.args)
        + len(args.kwonlyargs)
        + (1 if args.vararg else 0)
        + (1 if args.kwarg else 0)
    )


def _annotation(node: ast.AST | None) -> str:
    return unparse_ast(node, UNKNOWN)


def _parse_error(
    file_path: str,
    role: str,
    language: str,
    exc: SyntaxError,
) -> SignatureRecord:
    line = max(1, exc.lineno or 1)
    shape, shape_hash = canonical_shape([UNKNOWN], UNKNOWN)
    return SignatureRecord(
        language=language,
        language_family=LANGUAGE_FAMILY,
        adapter=AdapterId.PYTHON_AST,
        file=file_path,
        symbol="<parse_error>",
        normalized_symbol="parse error",
        container=None,
        start_line=line,
        end_line=line,
        role=role,
        type_source=SignatureTypeSource.UNKNOWN,
        parameters=[UNKNOWN],
        return_type=UNKNOWN,
        raw_signature="",
        canonical_shape=shape,
        shape_hash=shape_hash,
        body_line_count=0,
        body_shape="",
        body_shape_hash="",
        body_tree=None,
        body_tree_node_count=0,
        caveats=[f"python_parse_error: {exc.msg}"],
    )


def _function_parse_error(
    file_path: str,
    role: str,
    language: str,
    exc: SyntaxError,
) -> FunctionRecord:
    line = max(1, exc.lineno or 1)
    return FunctionRecord(
        language=language,
        file=file_path,
        symbol="<parse_error>",
        container=None,
        start_line=line,
        end_line=line,
        is_exported_or_public=False,
        is_async=False,
        parameter_count=0,
        branch_count=0,
        loop_count=0,
        return_count=0,
        max_nesting=0,
        role=role,
        source="",
        caveats=[f"python_parse_error: {exc.msg}"],
        extraction_confidence="low",
    )


def _attach_callsite_evidence(tree: ast.AST, records: list[SignatureRecord]) -> None:
    factories = {record.symbol for record in records if is_callable_return(record.return_type)}
    if not factories:
        return
    file_path = records[0].file if records else ""
    visitor = _CallsiteVisitor(factories, file_path)
    visitor.visit(tree)
    patterns_by_symbol = visitor.patterns_by_symbol()
    for record in records:
        symbol = record.symbol
        if symbol not in factories:
            continue
        patterns = patterns_by_symbol.get(symbol, [])
        evidence_kinds = [EvidenceKind.CALLABLE_FACTORY, *callsite_evidence_kinds(patterns)]
        record.is_callable_factory = True
        record.evidence_kinds = sorted(dict.fromkeys(evidence_kinds))
        record.callsite_patterns = tuple(patterns)


class _CallsiteVisitor(ast.NodeVisitor):
    def __init__(self, factories: set[str], file_path: str) -> None:
        self.factories = factories
        self.file_path = file_path
        self.patterns: dict[str, list[CallsitePattern]] = defaultdict(list)
        self.assigned: dict[str, tuple[str, int]] = {}
        self.call_counts: dict[str, int] = defaultdict(int)

    def patterns_by_symbol(self) -> dict[str, list[CallsitePattern]]:
        for variable, (symbol, line) in self.assigned.items():
            if self.call_counts[variable] > 1:
                self._add(
                    symbol,
                    EvidenceKind.CALLSITE_STORED_REUSE,
                    line,
                    variable=variable,
                    call_count=self.call_counts[variable],
                )
        return {
            symbol: sorted(
                patterns,
                key=lambda item: (item.line, item.kind),
            )
            for symbol, patterns in self.patterns.items()
        }

    def visit_Assign(self, node: ast.Assign) -> None:
        if symbol := self._factory_symbol(node.value):
            for target in node.targets:
                if name := _node_name(target, tuple_target=True):
                    self.assigned[name] = (symbol, node.lineno)
                if _is_cache_target(target):
                    self._add(symbol, EvidenceKind.CALLSITE_CACHED, node.lineno)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if type(node.func) is ast.Call:
            if symbol := self._factory_symbol(node.func):
                self._add(symbol, EvidenceKind.CALLSITE_IMMEDIATE, node.lineno)
        if name := _node_name(node.func, attribute=True):
            if name in self.assigned:
                self.call_counts[name] += 1
        for arg in node.args:
            if symbol := self._factory_symbol(arg):
                kind = (
                    EvidenceKind.CALLSITE_PIPELINE
                    if _is_pipeline_call(node)
                    else EvidenceKind.CALLSITE_REGISTERED
                )
                if kind == EvidenceKind.CALLSITE_REGISTERED and not _is_register_call(node):
                    continue
                self._add(symbol, kind, node.lineno)
        self.generic_visit(node)

    def _factory_symbol(self, node: ast.AST) -> str | None:
        if type(node) is not ast.Call:
            return None
        name = _node_name(node.func, attribute=True)
        return name if name in self.factories else None

    def _add(self, symbol: str, kind: str, line: int, **extra: object) -> None:
        variable = str(extra.get("variable", ""))
        item = CallsitePattern(
            kind=kind,
            symbol=symbol,
            file=self.file_path,
            line=line,
            variable=variable,
        )
        if item not in self.patterns[symbol]:
            self.patterns[symbol].append(item)


def _node_name(
    node: ast.AST,
    *,
    attribute: bool = False,
    tuple_target: bool = False,
) -> str | None:
    node_type = type(node)
    if node_type is ast.Name:
        return cast(ast.Name, node).id
    if attribute and node_type is ast.Attribute:
        return cast(ast.Attribute, node).attr
    if tuple_target and node_type is ast.Tuple:
        names = [_node_name(item, tuple_target=True) for item in cast(ast.Tuple, node).elts]
        return next((name for name in names if name), None)
    return None


def _is_cache_target(node: ast.AST) -> bool:
    if type(node) is ast.Subscript:
        target = node.value
        name = _node_name(target, attribute=True)
        return bool(name and "cache" in name.lower())
    if type(node) is ast.Attribute:
        return "cache" in node.attr.lower()
    return False


def _is_pipeline_call(node: ast.Call) -> bool:
    return _call_name_lower(node) in PIPELINE_CALL_NAMES


def _is_register_call(node: ast.Call) -> bool:
    name = _call_name_lower(node)
    return any(token in name for token in REGISTER_CALL_TOKENS)


def _call_name_lower(node: ast.Call) -> str:
    return (_node_name(node.func, attribute=True) or "").lower()
