from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from codeseam.analysis.relations.models import (
    CALLSITE_EVIDENCE_KINDS,
    EvidenceKind,
    RelationMemberContext,
)
from codeseam.analysis.signatures import CallsitePattern
from codeseam.platform import cached_identifier_tokens, text

CALLABLE_RETURN_RE = re.compile(r"\b(callable|Callable|function|Function)\b|=>|->")


def is_callable_return(return_type: object) -> bool:
    return bool(CALLABLE_RETURN_RE.search(text(return_type)))


def callsite_evidence_kinds(patterns: Iterable[CallsitePattern]) -> list[str]:
    kinds = (pattern.kind for pattern in patterns)
    return sorted(kind for kind in kinds if kind in CALLSITE_EVIDENCE_KINDS)


def callable_members(
    members: Sequence[RelationMemberContext],
) -> tuple[RelationMemberContext, ...]:
    return tuple(member for member in members if is_callable_return(member.return_type))


def callsite_patterns(members: Sequence[RelationMemberContext]) -> tuple[CallsitePattern, ...]:
    patterns: list[CallsitePattern] = []
    seen: set[tuple[str, str, str, int]] = set()
    for member in members:
        for pattern in member.callsite_patterns:
            key = (
                pattern.kind,
                pattern.symbol,
                pattern.file,
                pattern.line,
            )
            if key not in seen:
                patterns.append(pattern)
                seen.add(key)
    return tuple(
        sorted(
            patterns,
            key=lambda item: (
                item.file,
                item.line,
                item.kind,
            ),
        )
    )


PIPELINE_CALL_NAMES = frozenset({"filter", "flatmap", "map", "pipe", "reduce", "sorted", "then"})
REGISTER_CALL_TOKENS = frozenset(
    {"add", "handler", "listen", "on", "register", "route", "subscribe", "use"}
)
UNRESOLVED_RECEIVER = "?"


def is_cache_name(name: str) -> bool:
    return any(token.startswith("cache") for token in cached_identifier_tokens(name))


def last_name(dotted: str) -> str:
    return dotted.rsplit(".", 1)[-1]


@dataclass(slots=True)
class _Binding:
    symbol: str
    line: int
    calls: int = 0


@dataclass(slots=True)
class CallsiteTracker:
    """Lexically scoped evidence of how a file uses its own callable factories.

    Adapters walk their parse tree and report scopes, bindings and calls by
    dotted name (`handler`, `self.handler`). A later binding replaces an earlier
    one in its scope, and binding a non-factory value clears it, so a call only
    counts when the name still holds a factory result. Names the walk cannot
    resolve (`get().handler`) start with `UNRESOLVED_RECEIVER` and never bind.
    """

    factories: frozenset[str]
    file: str
    _scopes: list[dict[str, _Binding | None]] = field(default_factory=lambda: [{}])
    _stored: list[tuple[str, _Binding]] = field(default_factory=list)
    _patterns: dict[str, list[CallsitePattern]] = field(default_factory=dict)

    def enter(self, params: Iterable[str] = ()) -> None:
        self._scopes.append(dict.fromkeys(params))

    def exit(self) -> None:
        self._scopes.pop()

    def factory(self, callee: str | None) -> str | None:
        """The factory a call to `callee` invokes, unless a local name shadows it."""
        if not callee or (name := last_name(callee)) not in self.factories:
            return None
        if callee == name and (scope := self._scope_of(name)) is not None and scope[name] is None:
            return None
        return name

    def bind(self, target: str | None, symbol: str | None, line: int) -> None:
        if not target or target.startswith(UNRESOLVED_RECEIVER):
            return
        binding = _Binding(symbol, line) if symbol else None
        self._scopes[-1][target] = binding
        if binding is not None:
            self._stored.append((target, binding))

    def define(self, name: str | None, line: int) -> None:
        """A function or class definition; defining a factory does not shadow it."""
        if name not in self.factories:
            self.bind(name, None, line)

    def call(self, callee: str | None) -> None:
        if callee and (scope := self._scope_of(callee)) is not None:
            if (binding := scope[callee]) is not None:
                binding.calls += 1

    def argument(self, callee: str | None, symbol: str, line: int) -> None:
        """A factory result passed to `callee`: cached, piped or registered."""
        if kind := _argument_kind(callee or ""):
            self.add(kind, symbol, line)

    def add(self, kind: str, symbol: str, line: int, variable: str = "") -> None:
        item = CallsitePattern(kind, symbol, self.file, line, variable)
        items = self._patterns.setdefault(symbol, [])
        if item not in items:
            items.append(item)

    def patterns(self) -> dict[str, tuple[CallsitePattern, ...]]:
        for variable, binding in self._stored:
            if binding.calls > 1:
                self.add(EvidenceKind.CALLSITE_STORED_REUSE, binding.symbol, binding.line, variable)
        return {
            symbol: tuple(sorted(items, key=lambda item: (item.line, item.kind)))
            for symbol, items in self._patterns.items()
        }

    def _scope_of(self, name: str) -> dict[str, _Binding | None] | None:
        return next((scope for scope in reversed(self._scopes) if name in scope), None)


def _argument_kind(callee: str) -> EvidenceKind | None:
    receiver, _, name = callee.rpartition(".")
    if receiver and is_cache_name(last_name(receiver)):
        return EvidenceKind.CALLSITE_CACHED
    if name.lower() in PIPELINE_CALL_NAMES:
        return EvidenceKind.CALLSITE_PIPELINE
    if REGISTER_CALL_TOKENS & set(cached_identifier_tokens(name)):
        return EvidenceKind.CALLSITE_REGISTERED
    return None
