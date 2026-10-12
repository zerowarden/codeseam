"""How a module uses its own callable factories, tracked with lexical scope."""

from __future__ import annotations

import ast
from collections.abc import Iterator
from dataclasses import dataclass

from codeseam.analysis import (
    UNRESOLVED_RECEIVER,
    CallsitePattern,
    CallsiteTracker,
    EvidenceKind,
    is_cache_name,
)

type _FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda


@dataclass(frozen=True, slots=True)
class _Enter:
    params: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Exit:
    pass


@dataclass(frozen=True, slots=True)
class _Bind:
    targets: tuple[ast.expr, ...]
    symbol: str
    line: int


type _Step = ast.AST | _Enter | _Exit | _Bind


def callsite_patterns(
    tree: ast.AST, factories: frozenset[str], file_path: str
) -> dict[str, tuple[CallsitePattern, ...]]:
    tracker = CallsiteTracker(factories, file_path)
    stack: list[_Step] = [tree]
    while stack:
        step = stack.pop()
        if isinstance(step, _Enter):
            tracker.enter(step.params)
        elif isinstance(step, _Exit):
            tracker.exit()
        elif isinstance(step, _Bind):
            _bind(tracker, step)
        else:
            stack.extend(reversed(list(_visit(tracker, step))))
    return tracker.patterns()


def dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{dotted_name(node.value) or UNRESOLVED_RECEIVER}.{node.attr}"
    return None


def _visit(tracker: CallsiteTracker, node: ast.AST) -> Iterator[_Step]:
    """Record what `node` itself says, then yield its children in evaluation order."""
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
        yield from _function(tracker, node)
        return
    if isinstance(node, ast.ClassDef):
        tracker.define(node.name, node.lineno)
        yield from node.decorator_list
        yield from node.bases
        yield _Enter(())
        yield from node.body
        yield _Exit()
        return
    if isinstance(node, ast.Name | ast.Attribute) and isinstance(node.ctx, ast.Store):
        tracker.bind(dotted_name(node), None, node.lineno)
    elif isinstance(node, ast.Call):
        _call(tracker, node)
    yield from ast.iter_child_nodes(node)
    if bind := _factory_assignment(tracker, node):
        yield bind


def _function(tracker: CallsiteTracker, node: _FunctionNode) -> Iterator[_Step]:
    args = node.args
    params = [*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg]
    yield from (*args.defaults, *(default for default in args.kw_defaults if default))
    if isinstance(node, ast.Lambda):
        body: list[ast.AST] = [node.body]
    else:
        tracker.define(node.name, node.lineno)
        yield from node.decorator_list
        body = list(node.body)
    yield _Enter(tuple(param.arg for param in params if param))
    yield from body
    yield _Exit()


def _call(tracker: CallsiteTracker, node: ast.Call) -> None:
    callee = dotted_name(node.func)
    if isinstance(node.func, ast.Call):
        if symbol := tracker.factory(dotted_name(node.func.func)):
            tracker.add(EvidenceKind.CALLSITE_IMMEDIATE, symbol, node.lineno)
    tracker.call(callee)
    for arg in node.args:
        if isinstance(arg, ast.Call) and (symbol := tracker.factory(dotted_name(arg.func))):
            tracker.argument(callee, symbol, node.lineno)


def _factory_assignment(tracker: CallsiteTracker, node: ast.AST) -> _Bind | None:
    if isinstance(node, ast.Assign):
        targets, value = tuple(node.targets), node.value
    elif isinstance(node, ast.AnnAssign) and node.value is not None:
        targets, value = (node.target,), node.value
    else:
        return None
    if isinstance(value, ast.Call) and (symbol := tracker.factory(dotted_name(value.func))):
        return _Bind(targets, symbol, node.lineno)
    return None


def _bind(tracker: CallsiteTracker, step: _Bind) -> None:
    for target in step.targets:
        if isinstance(target, ast.Subscript | ast.Attribute) and _caches(target):
            tracker.add(EvidenceKind.CALLSITE_CACHED, step.symbol, step.line)
        if isinstance(target, ast.Name | ast.Attribute):
            tracker.bind(dotted_name(target), step.symbol, step.line)


def _caches(target: ast.Subscript | ast.Attribute) -> bool:
    if isinstance(target, ast.Attribute):
        return is_cache_name(target.attr)
    owner = dotted_name(target.value)
    return bool(owner and is_cache_name(owner.rsplit(".", 1)[-1]))


__all__ = ["callsite_patterns"]
