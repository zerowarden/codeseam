"""How a module uses its own callable factories, tracked with lexical scope."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from tree_sitter import Node

from codeseam.adapters.languages.ecmascript.runtime import line_no, node_text
from codeseam.adapters.languages.ecmascript.syntax_kinds import BODY_CALLABLE_TYPES
from codeseam.analysis import (
    UNRESOLVED_RECEIVER,
    CallsitePattern,
    CallsiteTracker,
    EvidenceKind,
    is_cache_name,
)

NAME_TYPES = frozenset({"identifier", "property_identifier", "private_property_identifier", "this"})
PARAMETER_PATTERN_FIELDS = {
    "required_parameter": "pattern",
    "optional_parameter": "pattern",
    "assignment_pattern": "left",
}


@dataclass(frozen=True, slots=True)
class _Enter:
    params: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Exit:
    pass


@dataclass(frozen=True, slots=True)
class _Bind:
    target: Node
    symbol: str
    line: int


type _Step = Node | _Enter | _Exit | _Bind


def callsite_patterns(
    source: bytes, root: Node, factories: frozenset[str], file_path: str
) -> dict[str, tuple[CallsitePattern, ...]]:
    walk = _Walk(source, CallsiteTracker(factories, file_path))
    stack: list[_Step] = [root]
    while stack:
        step = stack.pop()
        if isinstance(step, _Enter):
            walk.tracker.enter(step.params)
        elif isinstance(step, _Exit):
            walk.tracker.exit()
        elif isinstance(step, _Bind):
            walk.bind(step)
        else:
            stack.extend(reversed(list(walk.visit(step))))
    return walk.tracker.patterns()


@dataclass(frozen=True, slots=True)
class _Walk:
    source: bytes
    tracker: CallsiteTracker

    def visit(self, node: Node) -> Iterator[_Step]:
        """Record what `node` itself says, then yield its children in evaluation order."""
        if node.type in BODY_CALLABLE_TYPES:
            yield from self._function(node)
            return
        if node.type == "call_expression":
            self._call(node)
        target, value = _assignment(node)
        if target is not None:
            self.tracker.bind(self.dotted(target), None, line_no(node))
        yield from node.named_children
        if target is not None and (symbol := self._factory_call(value)):
            yield _Bind(target, symbol, line_no(node))

    def dotted(self, node: Node | None) -> str | None:
        if node is None:
            return None
        if node.type in NAME_TYPES:
            return node_text(self.source, node)
        if node.type == "member_expression":
            base = self.dotted(node.child_by_field_name("object")) or UNRESOLVED_RECEIVER
            return f"{base}.{node_text(self.source, node.child_by_field_name('property'))}"
        return None

    def bind(self, step: _Bind) -> None:
        if self._caches(step.target):
            self.tracker.add(EvidenceKind.CALLSITE_CACHED, step.symbol, step.line)
        self.tracker.bind(self.dotted(step.target), step.symbol, step.line)

    def _function(self, node: Node) -> Iterator[_Step]:
        if node.type == "function_declaration":
            self.tracker.define(self.dotted(node.child_by_field_name("name")), line_no(node))
        params = node.child_by_field_name("parameters") or node.child_by_field_name("parameter")
        yield _Enter(tuple(self._parameter_names(params)))
        yield from (child for child in node.named_children if child != params)
        yield _Exit()

    def _parameter_names(self, params: Node | None) -> Iterator[str]:
        if params is None:
            return
        for child in params.named_children if params.type == "formal_parameters" else (params,):
            pattern = child
            if field := PARAMETER_PATTERN_FIELDS.get(child.type):
                pattern = child.child_by_field_name(field) or child
            if pattern.type == "identifier" and (name := node_text(self.source, pattern)):
                yield name

    def _call(self, node: Node) -> None:
        function = node.child_by_field_name("function")
        callee = self.dotted(function)
        if symbol := self._factory_call(function):
            self.tracker.add(EvidenceKind.CALLSITE_IMMEDIATE, symbol, line_no(node))
        self.tracker.call(callee)
        arguments = node.child_by_field_name("arguments")
        for arg in arguments.named_children if arguments is not None else ():
            if symbol := self._factory_call(arg):
                self.tracker.argument(callee, symbol, line_no(node))

    def _factory_call(self, node: Node | None) -> str | None:
        if node is None or node.type != "call_expression":
            return None
        return self.tracker.factory(self.dotted(node.child_by_field_name("function")))

    def _caches(self, target: Node) -> bool:
        if target.type == "member_expression":
            name = node_text(self.source, target.child_by_field_name("property"))
        elif target.type == "subscript_expression":
            name = (self.dotted(target.child_by_field_name("object")) or "").rsplit(".", 1)[-1]
        else:
            return False
        return bool(name and is_cache_name(name))


def _assignment(node: Node) -> tuple[Node | None, Node | None]:
    if node.type == "variable_declarator":
        return node.child_by_field_name("name"), node.child_by_field_name("value")
    if node.type == "assignment_expression":
        return node.child_by_field_name("left"), node.child_by_field_name("right")
    return None, None


__all__ = ["callsite_patterns"]
