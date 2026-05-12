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
    candidates,
    signature_analysis_from_core,
)

FORCED_LSH_SIGNATURE = (1, 2, 3, 4)
LSH_ALWAYS_TRIGGER = 0


@pytest.fixture
def force_lsh(monkeypatch: pytest.MonkeyPatch) -> Callable[[], None]:
    def apply() -> None:
        monkeypatch.setattr(candidates, "LSH_CLUSTER_MEMBER_THRESHOLD", 2)
        monkeypatch.setattr(candidates, "LSH_PAIR_CAP_TRIGGER", LSH_ALWAYS_TRIGGER)

    return apply


@pytest.fixture
def force_lsh_collision(monkeypatch: pytest.MonkeyPatch) -> Callable[[], None]:
    def apply() -> None:
        monkeypatch.setattr(
            candidates,
            "minhash_signature",
            lambda _values, *, size: FORCED_LSH_SIGNATURE,
        )
        monkeypatch.setattr(
            candidates,
            "lsh_band_keys",
            lambda _signature, *, bands: ((0, (1, 2)),),
        )

    return apply


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
            role="source",
            type_source=SignatureTypeSource.INFERRED,
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
