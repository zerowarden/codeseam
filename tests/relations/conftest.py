from __future__ import annotations

from collections.abc import Callable

import pytest

from codeseam.analysis import (
    AdapterId,
    LanguageFamily,
    SignatureAnalysis,
    SignatureAnalysisFeatures,
    SignatureCore,
    SignatureOutputDetail,
    SignatureTypeSource,
    signature_analysis_from_core,
)


@pytest.fixture
def signature_analysis() -> Callable[..., SignatureAnalysis]:
    def build(  # noqa: PLR0913
        symbol: str,
        *,
        statements: tuple[str, ...] = ("RETURN:ARG0",),
        calls: tuple[str, ...] = (),
        controls: tuple[str, ...] = (),
        body_hash: str = "sha256:test",
        arg_reads: tuple[tuple[int, tuple[str, ...]], ...] = (),
        file: str = "src/example.py",
        role: str = "source",
    ) -> SignatureAnalysis:
        core = SignatureCore(
            language="python",
            language_family=LanguageFamily.PYTHON,
            adapter=AdapterId.PYTHON_AST,
            file=file,
            symbol=symbol,
            normalized_symbol=symbol,
            container=None,
            start_line=1,
            end_line=max(1, len(statements)),
            role=role,
            type_source=SignatureTypeSource.FALLBACK,
            parameters=("arg0",),
            return_type="object",
            canonical_shape="fn(arg0)->object",
            shape_hash="fn(arg0)->object",
            body_line_count=max(1, len(statements)),
            body_shape_hash=body_hash,
            body_tree_node_count=len(statements),
            statement_sequence=statements,
            call_tokens=calls,
            control_context_vector=controls,
            return_signature=tuple(item for item in statements if item.startswith("RETURN:")),
            signature_id=f"sig:{symbol}:{file}",
            function_id=f"fn:{symbol}:{file}",
        )
        return signature_analysis_from_core(
            core,
            features=SignatureAnalysisFeatures(
                signature_id=core.signature_id,
                statement_arg_reads=arg_reads,
            ),
            output=SignatureOutputDetail(signature_id=core.signature_id),
        )

    return build
