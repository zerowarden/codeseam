from __future__ import annotations

from pathlib import Path

import pytest

from codeseam.adapters.languages.python.signatures import extract_python_analysis
from codeseam.analysis import FunctionSemanticRole

FIXTURE = Path(__file__).parents[2] / "fixtures" / "signatures" / "semantic_role_surfaces.py"


@pytest.mark.parametrize(
    ("symbol", "expected_roles"),
    (
        (
            "__get__",
            {
                FunctionSemanticRole.PYTHON_SPECIAL_METHOD,
                FunctionSemanticRole.DESCRIPTOR_METHOD,
            },
        ),
        (
            "__add__",
            {
                FunctionSemanticRole.PYTHON_SPECIAL_METHOD,
                FunctionSemanticRole.OPERATOR_OVERLOAD,
            },
        ),
        (
            "__float__",
            {
                FunctionSemanticRole.PYTHON_SPECIAL_METHOD,
            },
        ),
        (
            "__tablename__",
            {FunctionSemanticRole.CUSTOM_DUNDER_OR_FRAMEWORK_HOOK},
        ),
        ("value", {FunctionSemanticRole.PROPERTY_ACCESSOR}),
        ("declared", {FunctionSemanticRole.PROPERTY_ACCESSOR}),
        (
            "query",
            {
                FunctionSemanticRole.ADAPTER_FORWARDER,
                FunctionSemanticRole.PUBLIC_API_MIRROR,
            },
        ),
        ("load", {FunctionSemanticRole.ADAPTER_FORWARDER}),
        (
            "execute",
            {
                FunctionSemanticRole.ADAPTER_FORWARDER,
                FunctionSemanticRole.PUBLIC_API_MIRROR,
            },
        ),
    ),
)
def test_python_adapter_classifies_semantic_roles(
    symbol: str,
    expected_roles: set[FunctionSemanticRole],
) -> None:
    records = extract_python_analysis(FIXTURE, "src/semantic_role_surfaces.py", "source").signatures
    roles = _roles_for(records, symbol)

    assert expected_roles <= roles


def test_python_adapter_classifies_typing_overload_stub() -> None:
    records = extract_python_analysis(FIXTURE, "src/semantic_role_surfaces.py", "source").signatures
    overload_records = [
        record
        for record in records
        if record.symbol == "get"
        and FunctionSemanticRole.TYPING_OVERLOAD.value in record.semantic_roles
    ]
    roles = _roles_for(records, "build")

    assert len(overload_records) == 1
    assert (
        FunctionSemanticRole.ABSTRACT_OR_INTERFACE_STUB.value in overload_records[0].semantic_roles
    )
    assert FunctionSemanticRole.ABSTRACT_OR_INTERFACE_STUB in roles


def test_python_adapter_public_api_mirror_requires_same_name_delegate() -> None:
    records = extract_python_analysis(FIXTURE, "src/semantic_role_surfaces.py", "source").signatures
    roles = _roles_for(records, "load")

    assert FunctionSemanticRole.ADAPTER_FORWARDER in roles
    assert FunctionSemanticRole.PUBLIC_API_MIRROR not in roles


def test_python_adapter_uses_repository_role_for_test_code() -> None:
    records = extract_python_analysis(
        FIXTURE,
        "tests/test_semantic_role_surfaces.py",
        "test",
    ).signatures

    assert all(FunctionSemanticRole.TEST_CODE.value in record.semantic_roles for record in records)


@pytest.mark.parametrize(
    ("path", "repository_role", "expected_role"),
    (
        ("examples/semantic_role_surfaces.py", "source", FunctionSemanticRole.EXAMPLE_CODE),
        ("src/generated_models.py", "source", FunctionSemanticRole.GENERATED_OR_CYTHON_BOUNDARY),
        ("src/model_cy.py", "source", FunctionSemanticRole.GENERATED_OR_CYTHON_BOUNDARY),
        ("src/vendor/api.py", "vendor", FunctionSemanticRole.GENERATED_OR_CYTHON_BOUNDARY),
        ("src/tests/semantic_role_surfaces.py", "source", FunctionSemanticRole.TEST_CODE),
        ("src/foo_test.py", "source", FunctionSemanticRole.TEST_CODE),
    ),
)
def test_python_adapter_classifies_non_source_path_roles(
    path: str,
    repository_role: str,
    expected_role: FunctionSemanticRole,
) -> None:
    records = extract_python_analysis(FIXTURE, path, repository_role).signatures

    assert all(expected_role.value in record.semantic_roles for record in records)


def _roles_for(records: tuple[object, ...], symbol: str) -> set[FunctionSemanticRole]:
    for record in records:
        if getattr(record, "symbol", "") == symbol:
            return {FunctionSemanticRole(role) for role in getattr(record, "semantic_roles", ())}
    raise AssertionError(f"Missing fixture symbol {symbol!r}.")
