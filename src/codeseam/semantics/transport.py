from __future__ import annotations

import json
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO, cast

from codeseam.platform import string_tuple
from codeseam.semantics.enrichment import (
    TREE_SITTER_FALLBACK,
    SemanticCallTarget,
    SemanticEnrichedItem,
    SemanticEnrichmentRequest,
    SemanticEnrichmentResult,
    SemanticMode,
    SemanticProjectSummary,
    SemanticProviderMetadata,
    SemanticProviderStatus,
    SemanticSymbolIdentity,
    semantic_provider_status,
)
from codeseam.semantics.provider import SemanticBudget

SEMANTIC_WORKER_PROTOCOL = "codeseam.semantic_worker.v1"
MAX_STDERR_CAVEAT_CHARS = 1_500
# Worker output goes to temporary files, and only this much is read back, so
# a misbehaving worker cannot exhaust memory.
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
BAD_RESPONSE = "semantic_worker_bad_response"


@dataclass(frozen=True, slots=True)
class _WorkerOutput:
    returncode: int
    stdout: str
    stderr: str
    truncated: bool


@dataclass(frozen=True, slots=True)
class StdioSemanticProvider:
    """Language-neutral stdio provider for external semantic workers.

    This is the process boundary, not the internal representation. Codeseam sends
    one compact request as NDJSON, expects one normalized response, and converts
    that payload back into typed semantic models immediately.
    """

    command: tuple[str, ...]
    cwd: Path | None = None
    env: Mapping[str, str] | None = None

    def __init__(
        self,
        command: Sequence[str],
        *,
        cwd: Path | str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        object.__setattr__(self, "command", tuple(command))
        object.__setattr__(self, "cwd", Path(cwd) if cwd is not None else None)
        object.__setattr__(self, "env", env)

    def enrich(
        self,
        request: SemanticEnrichmentRequest,
        budget: SemanticBudget,
    ) -> SemanticEnrichmentResult:
        worker_result = self._run_worker(request, budget)
        if isinstance(worker_result, SemanticEnrichmentResult):
            return worker_result
        return _completed_result(request, worker_result)

    def _run_worker(
        self,
        request: SemanticEnrichmentRequest,
        budget: SemanticBudget,
    ) -> _WorkerOutput | SemanticEnrichmentResult:
        if not self.command:
            return _failure(
                request,
                status=SemanticProviderStatus.UNAVAILABLE,
                reason="semantic_worker_command_missing",
            )
        try:
            with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
                completed = subprocess.run(
                    self.command,
                    input=_encode_request(request).encode(),
                    stdout=stdout,
                    stderr=stderr,
                    check=False,
                    timeout=_timeout_seconds(budget.request_timeout_ms),
                    cwd=self.cwd,
                    env=self.env,
                )
                body, truncated = _read_bounded(stdout)
                return _WorkerOutput(
                    completed.returncode, body, _read_bounded(stderr)[0], truncated
                )
        except FileNotFoundError:
            return _failure(
                request,
                status=SemanticProviderStatus.UNAVAILABLE,
                reason="semantic_worker_not_found",
            )
        except subprocess.TimeoutExpired:
            return _failure(
                request,
                status=SemanticProviderStatus.TIMED_OUT,
                reason="semantic_worker_timed_out",
            )
        except OSError as exc:
            return _failure(
                request,
                status=SemanticProviderStatus.FAILED,
                reason=f"semantic_worker_os_error:{type(exc).__name__}",
            )


def _read_bounded(file: IO[bytes]) -> tuple[str, bool]:
    file.seek(0)
    data = file.read(MAX_RESPONSE_BYTES + 1)
    return data[:MAX_RESPONSE_BYTES].decode(errors="replace"), len(data) > MAX_RESPONSE_BYTES


def _completed_result(
    request: SemanticEnrichmentRequest,
    completed: _WorkerOutput,
) -> SemanticEnrichmentResult:
    payload = _response_payload(completed)
    reason = payload if isinstance(payload, str) else _protocol_mismatch(request, payload)
    if reason:
        return _failure(
            request,
            status=SemanticProviderStatus.FAILED,
            reason=reason,
            stderr=completed.stderr,
        )
    return _decode_result(request, cast(Mapping[str, object], payload))


def _response_payload(completed: _WorkerOutput) -> Mapping[str, object] | str:
    """The decoded response, or the reason there is none."""

    if completed.truncated:
        return "semantic_worker_response_too_large"
    if completed.returncode != 0:
        return "semantic_worker_failed"
    line = _first_output_line(completed.stdout)
    if not line:
        return "semantic_worker_empty_response"
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return BAD_RESPONSE
    return cast(Mapping[str, object], payload) if isinstance(payload, Mapping) else BAD_RESPONSE


def _protocol_mismatch(request: SemanticEnrichmentRequest, payload: Mapping[str, object]) -> str:
    """Why the response does not answer this request, or "" when it does."""

    expected = {
        "protocol_version": SEMANTIC_WORKER_PROTOCOL,
        "request_id": request.request_id,
        "language": request.language,
    }
    mismatched = [key for key, value in expected.items() if payload.get(key) != value]
    project_key = _mapping(payload.get("project")).get("project_cache_key")
    if project_key not in {None, request.project_cache_key}:
        mismatched.append("project_cache_key")
    items = payload.get("items")
    returned = [
        item.get("signature_id")
        for item in (items if isinstance(items, list) else [])
        if isinstance(item, Mapping)
    ]
    requested = {item.signature_id for item in request.items}
    if len(set(returned)) != len(returned) or not set(returned) <= requested:
        mismatched.append("items")
    return f"semantic_worker_protocol_mismatch:{mismatched[0]}" if mismatched else ""


def _encode_request(request: SemanticEnrichmentRequest) -> str:
    payload = {
        "protocol_version": SEMANTIC_WORKER_PROTOCOL,
        "request_id": request.request_id,
        "language": request.language,
        "mode": request.mode,
        "repo_root": request.repo_root,
        "project_cache_key": request.project_cache_key,
        "config_path": request.config_path,
        "items": [_item_payload(item) for item in request.items],
    }
    return json.dumps(payload, separators=(",", ":")) + "\n"


def _item_payload(item: object) -> dict[str, object]:
    return {
        "signature_id": _attribute(item, "signature_id"),
        "relative_path": _attribute(item, "relative_path"),
        "start_line": _attribute(item, "start_line"),
        "end_line": _attribute(item, "end_line"),
        "callable_kind": _attribute(item, "callable_kind"),
        "symbol_hint": _attribute(item, "symbol_hint"),
        "start_byte": _attribute(item, "start_byte"),
        "end_byte": _attribute(item, "end_byte"),
    }


def _decode_result(
    request: SemanticEnrichmentRequest,
    payload: Mapping[str, object],
) -> SemanticEnrichmentResult:
    status = semantic_provider_status(payload.get("status"))
    return SemanticEnrichmentResult(
        request_id=_string(payload.get("request_id")) or request.request_id,
        language=_string(payload.get("language")) or request.language,
        mode=_mode(payload.get("mode"), request.mode),
        status=status,
        provider=_provider(payload.get("provider"), request.mode),
        project=_project(payload.get("project"), request),
        items=_items(payload.get("items")) if status == SemanticProviderStatus.READY else (),
        caveats=_strings(payload.get("caveats")),
        fallback="" if status == SemanticProviderStatus.READY else TREE_SITTER_FALLBACK,
    )


def _provider(value: object, mode: SemanticMode) -> SemanticProviderMetadata:
    data = _mapping(value)
    return SemanticProviderMetadata(
        name=_string(data.get("name")),
        mode=_mode(data.get("mode"), mode),
        compiler_available=_boolean(data.get("compiler_available")),
        compiler_version=_string(data.get("compiler_version")),
        typechecker_enabled=_boolean(data.get("typechecker_enabled")),
    )


def _project(value: object, request: SemanticEnrichmentRequest) -> SemanticProjectSummary:
    data = _mapping(value)
    return SemanticProjectSummary(
        project_cache_key=_string(data.get("project_cache_key")) or request.project_cache_key,
        config_path=_string(data.get("config_path")) or request.config_path,
        ownership_ambiguous=_boolean(data.get("ownership_ambiguous")),
        caveats=_strings(data.get("caveats")),
    )


def _items(value: object) -> tuple[SemanticEnrichedItem, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(_item(item) for item in value if isinstance(item, Mapping))


def _item(value: Mapping[str, object]) -> SemanticEnrichedItem:
    return SemanticEnrichedItem(
        signature_id=_string(value.get("signature_id")),
        resolved=_boolean(value.get("resolved")),
        ownership_ambiguous=_boolean(value.get("ownership_ambiguous")),
        symbol=_symbol(value.get("symbol")),
        overload_group_id=_optional_string(value.get("overload_group_id")),
        declaration_only=_boolean(value.get("declaration_only")),
        return_type=_string(value.get("return_type")),
        call_targets=_call_targets(value.get("call_targets")),
        caveats=_strings(value.get("caveats")),
    )


def _symbol(value: object) -> SemanticSymbolIdentity | None:
    if value is None:
        return None
    data = _mapping(value)
    return SemanticSymbolIdentity(
        name=_string(data.get("name")),
        declaration_file=_string(data.get("declaration_file")),
    )


def _call_targets(value: object) -> tuple[SemanticCallTarget, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(_call_target(item) for item in value if isinstance(item, Mapping))


def _call_target(value: Mapping[str, object]) -> SemanticCallTarget:
    return SemanticCallTarget(
        call_token=_string(value.get("call_token")),
        resolved=_boolean(value.get("resolved")),
        symbol_name=_string(value.get("symbol_name")),
        declaration_file=_string(value.get("declaration_file")),
        caveats=_strings(value.get("caveats")),
    )


def _failure(
    request: SemanticEnrichmentRequest,
    *,
    status: SemanticProviderStatus,
    reason: str,
    stderr: str = "",
) -> SemanticEnrichmentResult:
    caveats = (reason, *_stderr_caveats(stderr))
    return SemanticEnrichmentResult(
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


def _stderr_caveats(stderr: str) -> tuple[str, ...]:
    excerpt = stderr.strip()
    if not excerpt:
        return ()
    if len(excerpt) > MAX_STDERR_CAVEAT_CHARS:
        excerpt = f"{excerpt[:MAX_STDERR_CAVEAT_CHARS]}..."
    return (f"semantic_worker_stderr:{excerpt}",)


def _first_output_line(stdout: str) -> str:
    for line in stdout.splitlines():
        if line.strip():
            return line
    return ""


def _timeout_seconds(milliseconds: int) -> float:
    return max(1, milliseconds) / 1_000


def _attribute(item: object, name: str) -> object:
    return getattr(item, name)


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _mode(value: object, default: SemanticMode) -> SemanticMode:
    if isinstance(value, SemanticMode):
        return value
    if not isinstance(value, str):
        return default
    try:
        return SemanticMode(value)
    except ValueError:
        return default


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    return _string(value)


def _strings(value: object) -> tuple[str, ...]:
    return string_tuple(value)


def _boolean(value: object) -> bool:
    return value if isinstance(value, bool) else False


__all__ = [
    "SEMANTIC_WORKER_PROTOCOL",
    "StdioSemanticProvider",
]
