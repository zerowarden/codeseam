from __future__ import annotations

import pytest

from codeseam.semantics import (
    SemanticEnrichedItem,
    SemanticEnrichmentItem,
    SemanticEnrichmentRequest,
    SemanticEnrichmentResult,
    SemanticMode,
    SemanticProjectSummary,
    SemanticProviderMetadata,
    SemanticProviderStatus,
    semantic_mode,
    semantic_provider_status,
)

BYTE_START = 10
BYTE_END = 80


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (SemanticMode.AUTO, SemanticMode.AUTO),
        ("project", SemanticMode.PROJECT),
        ("missing", SemanticMode.OFF),
        (None, SemanticMode.OFF),
    ],
)
def test_semantic_mode_is_generic_and_safe(value: object, expected: SemanticMode) -> None:
    assert semantic_mode(value) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (SemanticProviderStatus.READY, SemanticProviderStatus.READY),
        ("timed_out", SemanticProviderStatus.TIMED_OUT),
        ("provider_returned_new_status", SemanticProviderStatus.UNAVAILABLE),
        (None, SemanticProviderStatus.UNAVAILABLE),
    ],
)
def test_provider_status_unknowns_fall_back_to_unavailable(
    value: object,
    expected: SemanticProviderStatus,
) -> None:
    assert semantic_provider_status(value) is expected


@pytest.mark.parametrize("language", ["TypeScript", "Rust", "Swift"])
def test_enrichment_request_is_language_neutral(language: str) -> None:
    request = SemanticEnrichmentRequest(
        request_id=f"{language.lower()}-request",
        language=language,
        mode=SemanticMode.AUTO,
        repo_root="/repo",
        project_cache_key="sha256:project",
        config_path=f"/repo/{language.lower()}.config",
        items=(
            SemanticEnrichmentItem(
                signature_id="sig_1",
                relative_path=f"src/main.{_extension(language)}",
                start_line=3,
                end_line=8,
                callable_kind="function",
                symbol_hint="run",
            ),
        ),
    )

    assert request.language == language
    assert request.items[0].signature_id == "sig_1"
    assert request.items[0].line_span == (3, 8)
    assert request.items[0].start_byte is None
    assert request.items[0].end_byte is None


def test_enrichment_item_rejects_invalid_spans() -> None:
    with pytest.raises(ValueError, match="end_line"):
        SemanticEnrichmentItem(
            signature_id="sig_bad",
            relative_path="src/app.ts",
            start_line=8,
            end_line=3,
            callable_kind="function",
            symbol_hint="run",
        )


def test_enrichment_item_allows_optional_byte_offsets() -> None:
    item = SemanticEnrichmentItem(
        signature_id="sig_1",
        relative_path="src/app.ts",
        start_line=1,
        end_line=3,
        callable_kind="function",
        symbol_hint="run",
        start_byte=BYTE_START,
        end_byte=BYTE_END,
    )

    assert item.start_byte == BYTE_START
    assert item.end_byte == BYTE_END


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (SemanticProviderStatus.DISABLED, "semantic_mode_off"),
        (SemanticProviderStatus.UNAVAILABLE, "node_helper_missing"),
        (SemanticProviderStatus.TIMED_OUT, "project_load_timeout"),
    ],
)
def test_unavailable_results_preserve_tree_sitter_fallback(
    status: SemanticProviderStatus,
    reason: str,
) -> None:
    result = SemanticEnrichmentResult.unavailable(
        _request(),
        status=status,
        reason=reason,
    )

    assert result.status is status
    assert result.items == ()
    assert result.fallback == "tree_sitter_only"
    assert reason in result.caveats


def test_ready_result_can_be_successfully_empty() -> None:
    request = _request()
    result = SemanticEnrichmentResult(
        request_id=request.request_id,
        language=request.language,
        mode=request.mode,
        status=SemanticProviderStatus.READY,
        provider=SemanticProviderMetadata(
            name="fake_semantic_provider",
            mode=SemanticMode.AUTO,
        ),
        project=SemanticProjectSummary(
            project_cache_key=request.project_cache_key,
            config_path=request.config_path,
        ),
        items=(),
    )

    assert result.status is SemanticProviderStatus.READY
    assert result.provider.name == "fake_semantic_provider"
    assert result.items == ()


def test_item_caveats_are_typed_per_signature() -> None:
    item = SemanticEnrichedItem(
        signature_id="sig_unsupported",
        resolved=False,
        caveats=("unsupported_node_kind",),
    )

    assert item.signature_id == "sig_unsupported"
    assert item.resolved is False
    assert item.caveats == ("unsupported_node_kind",)


def _request() -> SemanticEnrichmentRequest:
    return SemanticEnrichmentRequest(
        request_id="request-1",
        language="TypeScript",
        mode=SemanticMode.AUTO,
        repo_root="/repo",
        project_cache_key="sha256:project",
        config_path="/repo/tsconfig.json",
        items=(),
    )


def _extension(language: str) -> str:
    return {
        "Rust": "rs",
        "Swift": "swift",
        "TypeScript": "ts",
    }[language]
