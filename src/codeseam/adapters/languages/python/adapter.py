from __future__ import annotations

from typing import cast

from codeseam.adapters.languages.base import (
    LanguageAdapterAnalysis,
    LanguageAnalysisContext,
    StaticLanguageSupport,
)
from codeseam.adapters.languages.capabilities import AdapterCapabilities
from codeseam.adapters.languages.python.analysis import (
    PythonAnalysis,
    PythonFunctionNode,
    parse_python,
)
from codeseam.adapters.languages.python.manifests import PYTHON_MANIFEST_MATCHERS
from codeseam.adapters.languages.python.signatures import (
    extract_python_analysis,
    extract_python_relation_detail,
    extract_python_relation_detail_source,
    function_node_index,
)
from codeseam.adapters.languages.relation_detail import RelationDetailRequest
from codeseam.analysis import AdapterId, FunctionRecord, SignatureAnalysisFeatures


class PythonAstAdapter(StaticLanguageSupport):
    adapter_id = AdapterId.PYTHON_AST
    language_id = "python"
    languages = frozenset({"Python"})
    manifest_matchers = PYTHON_MANIFEST_MATCHERS
    capabilities = AdapterCapabilities(
        syntax_frontend="python_ast",
        policy_constants=True,
        relation_detail=True,
        compiler_semantics=True,
    )

    def extract_analysis(self, context: LanguageAnalysisContext) -> LanguageAdapterAnalysis:
        return extract_python_analysis(
            context.path,
            context.relative_path,
            context.role,
            language=self.language_id,
            analysis=_python_analysis(context),
        )

    def hydrate_relation_detail(
        self,
        request: RelationDetailRequest,
    ) -> SignatureAnalysisFeatures:
        core = request.signature.core
        analysis = _cached_python_analysis(request.context)
        node = (
            _python_function_node(analysis, core.symbol, core.start_line)
            if analysis is not None
            else None
        )
        if node is not None:
            return extract_python_relation_detail(node, core.signature_id)
        return extract_python_relation_detail_source(
            _python_function_source(request.context, request.function),
            core.signature_id,
        )


def _python_analysis(context: LanguageAnalysisContext) -> PythonAnalysis | None:
    if context.run_cache is not None:
        return context.run_cache.analysis(context, "python_ast", lambda: parse_python(context.path))
    return None


def _cached_python_analysis(context: LanguageAnalysisContext) -> PythonAnalysis | None:
    if context.run_cache is None:
        return None
    return cast(PythonAnalysis | None, context.run_cache.cached_analysis(context, "python_ast"))


def _python_function_node(
    analysis: PythonAnalysis,
    symbol: str,
    start_line: int,
) -> PythonFunctionNode | None:
    tree = analysis.tree
    if tree is None:
        return None
    if not analysis.function_nodes:
        analysis.function_nodes = function_node_index(tree)
    return analysis.function_nodes.get((symbol, start_line))


def _python_function_source(
    context: LanguageAnalysisContext,
    function: FunctionRecord | None,
) -> str:
    if function is None:
        return ""
    try:
        source = (
            context.run_cache.source_bytes(context).decode("utf-8", errors="replace")
            if context.run_cache is not None
            else context.path.read_text(encoding="utf-8", errors="replace")
        )
    except OSError:
        return ""
    lines = source.splitlines()
    return "\n".join(lines[function.start_line - 1 : function.end_line])


__all__ = ["PythonAstAdapter"]
