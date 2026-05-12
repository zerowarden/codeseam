from __future__ import annotations


class LanguageAdapter(Protocol):
    adapter_id: str
    languages: frozenset[str]
    extensions: frozenset[str]

    def supports_path(self, path: Path) -> bool: ...

    def supports_language(self, language: str) -> bool: ...

    def extract_analysis(self, context: LanguageAnalysisContext) -> LanguageAdapterAnalysis: ...


class ECMAScriptTypeScriptTreeSitterAdapter(StaticLanguageSupport):
    adapter_id = ADAPTER_ID
    languages = JS_TS_LANGUAGES
    extensions = JS_TS_EXTENSIONS

    def extract_analysis(self, context: LanguageAnalysisContext) -> LanguageAdapterAnalysis:
        return _extract_ecmascript_analysis(context)


class PythonAstAdapter(StaticLanguageSupport):
    adapter_id = "python_ast"
    languages = frozenset({"Python"})
    extensions = frozenset({".py"})

    def extract_analysis(self, context: LanguageAnalysisContext) -> LanguageAdapterAnalysis:
        return extract_python_analysis(context.path, context.relative_path, context.role, _python_analysis(context))
