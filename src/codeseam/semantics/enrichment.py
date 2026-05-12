from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

TREE_SITTER_FALLBACK = "tree_sitter_only"


class SemanticMode(StrEnum):
    """How Codeseam may use external semantic providers for a run.

    This mode is language-neutral. TypeScript may use a Node sidecar later,
    Rust may use rust-analyzer, and Swift may use compiler services. The core
    pipeline should make the same safety decision for all of them.
    """

    OFF = "off"
    AUTO = "auto"
    PROJECT = "project"
    REQUIRED = "required"


SEMANTIC_MODE_BY_VALUE = {
    SemanticMode.OFF.value: SemanticMode.OFF,
    SemanticMode.AUTO.value: SemanticMode.AUTO,
    SemanticMode.PROJECT.value: SemanticMode.PROJECT,
    SemanticMode.REQUIRED.value: SemanticMode.REQUIRED,
}


class SemanticProviderStatus(StrEnum):
    """Provider availability for one semantic enrichment request."""

    DISABLED = "disabled"
    UNAVAILABLE = "unavailable"
    READY = "ready"
    TIMED_OUT = "timed_out"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class SemanticEnrichmentItem:
    """A compact source span selected for semantic enrichment.

    Tree-sitter or a native parser owns baseline extraction. Semantic providers
    receive spans and identifiers only, which keeps batch requests small and
    avoids making provider calls depend on raw source payloads.
    """

    signature_id: str
    relative_path: str
    start_line: int
    end_line: int
    callable_kind: str
    symbol_hint: str = ""
    start_byte: int | None = None
    end_byte: int | None = None

    def __post_init__(self) -> None:
        _validate_range("line", self.start_line, self.end_line)
        if self.start_byte is None and self.end_byte is None:
            return
        if self.start_byte is None or self.end_byte is None:
            raise ValueError("start_byte and end_byte must be provided together")
        _validate_range("byte", self.start_byte, self.end_byte)

    @property
    def line_span(self) -> tuple[int, int]:
        return self.start_line, self.end_line


@dataclass(frozen=True, slots=True)
class SemanticEnrichmentRequest:
    """A language-neutral batch request for selected semantic facts."""

    request_id: str
    language: str
    mode: SemanticMode
    repo_root: str
    project_cache_key: str
    config_path: str
    items: tuple[SemanticEnrichmentItem, ...]


@dataclass(frozen=True, slots=True)
class SemanticProviderMetadata:
    """Provider identity attached to semantic results."""

    name: str = ""
    mode: SemanticMode = SemanticMode.OFF


@dataclass(frozen=True, slots=True)
class SemanticProjectSummary:
    """Project facts returned by a semantic provider."""

    project_cache_key: str = ""
    config_path: str = ""
    ownership_ambiguous: bool = False
    caveats: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SemanticSymbolIdentity:
    """Resolved symbol identity in a provider-neutral shape."""

    name: str = ""
    declaration_file: str = ""


@dataclass(frozen=True, slots=True)
class SemanticCallTarget:
    """Resolved target for a selected call inside an enriched item."""

    call_token: str
    resolved: bool
    symbol_name: str = ""
    declaration_file: str = ""
    caveats: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SemanticEnrichedItem:
    """Compact semantic facts for one selected signature."""

    signature_id: str
    resolved: bool
    ownership_ambiguous: bool = False
    symbol: SemanticSymbolIdentity | None = None
    overload_group_id: str | None = None
    declaration_only: bool = False
    return_type: str = ""
    call_targets: tuple[SemanticCallTarget, ...] = ()
    caveats: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SemanticEnrichmentResult:
    """Typed semantic provider response.

    A failed or unavailable provider is still a valid result. That lets the
    pipeline continue with parser-only evidence and attach explicit caveats
    instead of throwing during ordinary analysis.
    """

    request_id: str
    language: str
    mode: SemanticMode
    status: SemanticProviderStatus
    provider: SemanticProviderMetadata
    project: SemanticProjectSummary
    items: tuple[SemanticEnrichedItem, ...] = ()
    caveats: tuple[str, ...] = ()
    fallback: str = ""

    @classmethod
    def unavailable(
        cls,
        request: SemanticEnrichmentRequest,
        *,
        status: SemanticProviderStatus = SemanticProviderStatus.UNAVAILABLE,
        reason: str = "",
    ) -> SemanticEnrichmentResult:
        caveats = (reason,) if reason else ()
        return cls(
            request_id=request.request_id,
            language=request.language,
            mode=request.mode,
            status=status,
            provider=SemanticProviderMetadata(mode=request.mode),
            project=SemanticProjectSummary(
                project_cache_key=request.project_cache_key,
                config_path=request.config_path,
            ),
            caveats=caveats,
            fallback=TREE_SITTER_FALLBACK,
        )


def semantic_mode(value: object) -> SemanticMode:
    if isinstance(value, SemanticMode):
        return value
    if not isinstance(value, str):
        return SemanticMode.OFF
    return SEMANTIC_MODE_BY_VALUE.get(value, SemanticMode.OFF)


def semantic_provider_status(value: object) -> SemanticProviderStatus:
    if isinstance(value, SemanticProviderStatus):
        return value
    if not isinstance(value, str):
        return SemanticProviderStatus.UNAVAILABLE
    try:
        return SemanticProviderStatus(value)
    except ValueError:
        return SemanticProviderStatus.UNAVAILABLE


def _validate_range(label: str, start: int, end: int) -> None:
    if start < 0:
        raise ValueError(f"start_{label} must be non-negative")
    if end < start:
        raise ValueError(f"end_{label} must be greater than or equal to start_{label}")


__all__ = [
    "TREE_SITTER_FALLBACK",
    "SemanticCallTarget",
    "SemanticEnrichedItem",
    "SemanticEnrichmentItem",
    "SemanticEnrichmentRequest",
    "SemanticEnrichmentResult",
    "SemanticMode",
    "SemanticProjectSummary",
    "SemanticProviderMetadata",
    "SemanticProviderStatus",
    "SemanticSymbolIdentity",
    "semantic_mode",
    "semantic_provider_status",
]
