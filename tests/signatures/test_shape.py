from __future__ import annotations

import pytest

from codeseam.analysis import (
    AdapterId,
    FunctionIR,
    LanguageFamily,
    ParamIR,
    SignatureTypeSource,
    canonical_shape,
    signature_shape,
)


@pytest.mark.parametrize(
    ("parameters", "return_type", "expected"),
    [
        pytest.param(["T"], "T", "fn(G0)->G0", id="same-generic"),
        pytest.param(["U"], "U", "fn(G0)->G0", id="renamed-generic"),
        pytest.param(["T"], "U", "fn(G0)->G1", id="distinct-generics"),
    ],
)
def test_canonical_shape_normalizes_generic_relationships(
    parameters: list[str],
    return_type: str,
    expected: str,
) -> None:
    assert canonical_shape(parameters, return_type)[0] == expected


def test_signature_shape_can_be_derived_from_function_ir() -> None:
    shape = signature_shape(
        FunctionIR(
            language="typescript",
            language_family=LanguageFamily.ECMASCRIPT_TYPESCRIPT,
            file="src/app.ts",
            name="identity",
            container=None,
            kind="function",
            start_line=1,
            end_line=1,
            is_async=False,
            is_exported_or_public=True,
            params=(ParamIR("T"),),
            return_annotation="T",
            declared_generics=("T",),
            raw_signature="function identity<T>(value: T): T",
            source_text="",
            body_text="",
            body_line_count=1,
            branch_count=0,
            loop_count=0,
            return_count=0,
            max_nesting=0,
            adapter=AdapterId.TREESITTER_ECMASCRIPT_TYPESCRIPT,
            extraction_confidence="high",
            caveats=(),
        )
    )

    assert shape.canonical_shape == "fn(G0)->G0"
    assert shape.type_source is SignatureTypeSource.DECLARED_SYNTAX
    assert shape.caveats == []

