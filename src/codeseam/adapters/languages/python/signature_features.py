from __future__ import annotations

import ast
import zlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import cast

from codeseam.analysis import (
    CalleeShape,
    CallFingerprint,
    DataflowEdge,
    DataflowGraph,
    DataflowNode,
    ExpressionShape,
    ParameterUseVector,
)
from codeseam.analysis.signatures.model import OperationCompact, OperationFeatures, OperationFlow
from codeseam.platform import cached_identifier_tokens

type _CollectResult = tuple[int, int]
type _CalleeParts = tuple[tuple[str, ...], tuple[str, ...], str, str, tuple[str, ...]]

BRANCH_NODES = (ast.If, ast.IfExp, ast.Match, ast.Try, ast.ExceptHandler, ast.BoolOp)
LOOP_NODES = (ast.For, ast.AsyncFor, ast.While, ast.comprehension)
NESTING_NODES = BRANCH_NODES + LOOP_NODES + (ast.With, ast.AsyncWith)
BRANCH_NODE_TYPES = frozenset(BRANCH_NODES)
LOOP_NODE_TYPES = frozenset(LOOP_NODES)
NESTING_NODE_TYPES = frozenset(NESTING_NODES)
CONTROL_LOOP_NODE_TYPES = frozenset((ast.For, ast.AsyncFor, ast.While))
CONTROL_BRANCH_NODE_TYPES = frozenset((ast.If, ast.Match))
NORMALIZATION_TRANSFORM_METHODS = frozenset({"decode", "encode"})
STRUCTURE_HASH_OFFSET = 0


@dataclass(frozen=True, slots=True)
class _CallFacts:
    token: str
    namespace_tokens: tuple[str, ...]
    name_tokens: tuple[str, ...]
    call_kind: str
    receiver_base: str
    receiver_path: tuple[str, ...]
    arg_roles: tuple[str, ...]
    kwarg_shape: tuple[tuple[str, str], ...]
    read_mask: int
    callee_name: str


@dataclass(slots=True)
class _MutableParameterUse:
    access_paths: list[str] = field(default_factory=list)
    receiver_of_calls: list[str] = field(default_factory=list)
    passed_as_argument_to: list[str] = field(default_factory=list)
    returned: bool = False


def operation_features(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    include_relation_detail: bool = False,
    include_flow: bool = False,
) -> OperationFeatures:
    """Extract Python function features in two cost tiers.

    The default tier feeds ``SignatureCore`` and is paid for every function on
    the cold path. Relation-detail features are richer graph/parameter/literal
    facts used only after clustering decides a function may participate in
    relation scoring, so callers must opt into them explicitly.
    """
    args = _arg_roles(node.args)
    context = _FeatureContext.from_function(node, args)
    sequence = _statement_sequence(node, context)
    needs_call_facts = include_relation_detail or include_flow
    call_facts = (
        tuple(context.call_facts(call) for call in context.calls) if needs_call_facts else ()
    )
    call_tokens = (
        tuple(facts.token for facts in call_facts)
        if needs_call_facts
        else tuple(context.call_token(call) for call in context.calls)
    )
    defaults = _parameter_defaults(node.args, args)
    relation_detail = (
        _relation_detail_features(node, context, sequence, call_facts, defaults)
        if include_relation_detail
        else _RelationDetail()
    )
    return OperationFeatures(
        compact=OperationCompact(
            statement_sequence=tuple(sequence),
            call_tokens=call_tokens,
            parameter_default_roles=tuple(sorted(defaults.items())),
            normalization_transform_tokens=relation_detail.normalization_transform_tokens,
            graph_features=relation_detail.graph_features,
            literal_shapes=relation_detail.literal_shapes,
            receiver_shapes=relation_detail.receiver_shapes,
            parameter_features=tuple(sorted(relation_detail.parameter_features.items())),
            statement_arg_reads=relation_detail.statement_arg_reads,
            control_context_vector=tuple(context.control_context_vector),
            body_shape=context.body_shape,
            body_shape_hash=context.body_shape_hash,
            body_tree_node_count=context.body_tree_node_count,
            branch_count=context.branch_count,
            loop_count=context.loop_count,
            return_count=context.return_count,
            max_nesting=context.max_nesting,
        ),
        flow=(
            OperationFlow(
                call_fingerprints=tuple(context.call_fingerprint(call) for call in context.calls),
                parameter_use_vectors=tuple(
                    sorted(_parameter_use_vectors(context, call_facts).items())
                ),
                parameter_default_roles=tuple(sorted(defaults.items())),
                local_dataflow_graph=_local_dataflow_graph(node, context, sequence),
            )
            if include_flow
            else OperationFlow(
                call_fingerprints=(),
                parameter_use_vectors=(),
                parameter_default_roles=tuple(sorted(defaults.items())),
                local_dataflow_graph=DataflowGraph(),
            )
        ),
    )


@dataclass(frozen=True, slots=True)
class _RelationDetail:
    normalization_transform_tokens: tuple[str, ...] = ()
    graph_features: frozenset[str] = frozenset()
    literal_shapes: frozenset[str] = frozenset()
    receiver_shapes: frozenset[str] = frozenset()
    parameter_features: dict[str, frozenset[str]] = field(default_factory=dict)
    statement_arg_reads: tuple[tuple[int, tuple[str, ...]], ...] = ()


def _relation_detail_features(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    context: _FeatureContext,
    sequence: list[str],
    call_facts: tuple[_CallFacts, ...],
    defaults: dict[str, str],
) -> _RelationDetail:
    return _RelationDetail(
        normalization_transform_tokens=tuple(
            token for facts in call_facts if (token := _normalization_transform_token(facts))
        ),
        graph_features=_compact_graph_features(node, context, sequence),
        literal_shapes=_literal_shapes(call_facts, defaults),
        receiver_shapes=_receiver_shapes(call_facts),
        parameter_features=_parameter_features(context, call_facts),
        statement_arg_reads=_statement_arg_reads(node, context),
    )


@dataclass(slots=True)
class _FeatureContext:
    args: dict[str, str]
    locals_: set[str]
    calls: tuple[ast.Call, ...]
    attributes: tuple[ast.Attribute, ...]
    returns: tuple[ast.Return, ...]
    control_context_vector: list[str]
    body_shape: str
    body_shape_hash: str
    body_tree_node_count: int
    branch_count: int
    loop_count: int
    return_count: int
    max_nesting: int
    _arg_read_masks: dict[int, int] = field(default_factory=dict)
    _load_reads: dict[int, set[str]] = field(default_factory=dict)
    _call_tokens: dict[int, str] = field(default_factory=dict)
    _call_facts: dict[int, _CallFacts] = field(default_factory=dict)
    _call_fingerprints: dict[int, CallFingerprint] = field(default_factory=dict)

    @classmethod
    def from_function(
        cls,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        args: dict[str, str],
    ) -> _FeatureContext:
        collector = _FunctionCollector(args)
        body_shape_hash, body_tree_node_count = collector.collect_function(node)
        return cls(
            args=args,
            locals_=collector.locals_,
            calls=tuple(collector.calls),
            attributes=tuple(collector.attributes),
            returns=tuple(collector.returns),
            control_context_vector=sorted(collector.controls),
            body_shape="",
            body_shape_hash=body_shape_hash,
            body_tree_node_count=body_tree_node_count,
            branch_count=collector.branch_count,
            loop_count=collector.loop_count,
            return_count=collector.return_count,
            max_nesting=collector.max_nesting,
            _arg_read_masks=collector.arg_read_masks,
            _load_reads=collector.load_reads,
        )

    def arg_read_mask(self, node: ast.AST | None) -> int:
        if node is None:
            return 0
        return self._arg_read_masks.get(id(node), 0)

    def arg_reads(self, node: ast.AST | None) -> tuple[str, ...]:
        return _roles_from_mask(self.arg_read_mask(node))

    def iter_arg_reads(self, node: ast.AST | None) -> Iterable[str]:
        return _iter_roles_from_mask(self.arg_read_mask(node))

    def local_reads(self, node: ast.AST) -> set[str]:
        return self._load_reads.get(id(node), set()) & self.locals_

    def call_facts(self, call: ast.Call) -> _CallFacts:
        key = id(call)
        facts = self._call_facts.get(key)
        if facts is None:
            facts = _call_facts(call, self)
            self._call_facts[key] = facts
            self._call_tokens[key] = facts.token
        return facts

    def call_fingerprint(self, call: ast.Call) -> CallFingerprint:
        key = id(call)
        fingerprint = self._call_fingerprints.get(key)
        if fingerprint is None:
            fingerprint = _call_fingerprint(self.call_facts(call))
            self._call_fingerprints[key] = fingerprint
        return fingerprint

    def call_token(self, call: ast.Call) -> str:
        key = id(call)
        token = self._call_tokens.get(key)
        if token is None:
            token = _call_token_for_call(call, self)
            self._call_tokens[key] = token
        return token


@dataclass(slots=True)
class _FunctionCollector:
    """Collect function-level structural facts in one AST pass.

    `arg_read_masks` are retained by node because call/value roles query nested
    expressions. Local-name reads are intentionally stored only for top-level
    statements: compact dataflow features only need statement-local reads, and
    propagating `set[str]` through every AST node is a cold-path allocation cost.
    """

    args: dict[str, str]
    arg_masks: dict[str, int] = field(init=False)
    locals_: set[str] = field(default_factory=set)
    calls: list[ast.Call] = field(default_factory=list)
    attributes: list[ast.Attribute] = field(default_factory=list)
    returns: list[ast.Return] = field(default_factory=list)
    controls: set[str] = field(default_factory=set)
    arg_read_masks: dict[int, int] = field(default_factory=dict)
    load_reads: dict[int, set[str]] = field(default_factory=dict)
    current_statement_loads: set[str] | None = None
    branch_count: int = 0
    loop_count: int = 0
    return_count: int = 0
    max_nesting: int = 0
    structure_hash: int = STRUCTURE_HASH_OFFSET

    def __post_init__(self) -> None:
        self.arg_masks = _arg_masks(self.args)

    def collect_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> tuple[str, int]:
        body_node_count = 1
        for child in node.body:
            previous_loads = self.current_statement_loads
            # Local-flow features only query reads at top-level statement
            # boundaries. Keep one mutable read set per statement instead of
            # allocating and unioning a set for every AST node in the subtree.
            statement_loads: set[str] = set()
            self.current_statement_loads = statement_loads
            try:
                item = self.collect(child)
            finally:
                self.current_statement_loads = previous_loads
            self.load_reads[id(child)] = statement_loads
            body_node_count += item[1]
        return _format_shape_hash(self.structure_hash), body_node_count

    def collect(self, value: object, depth: int = 0) -> _CollectResult:
        value_type = type(value)
        if value_type is ast.Name:
            name: ast.Name = value  # type: ignore[assignment]
            return self._name(name)
        if value_type is ast.arg:
            arg: ast.arg = value  # type: ignore[assignment]
            return self._arg(arg)
        if value_type is ast.Constant:
            constant: ast.Constant = value  # type: ignore[assignment]
            self._add_shape_token_triple(
                "Constant",
                type(constant.value).__name__,
                repr(constant.value),
            )
            return self._record(
                constant,
                0,
                1,
            )
        if isinstance(value, ast.AST):
            next_depth = self._record_node(value, depth)
            arg_read_mask = 0
            node_count = 1
            for _, item in ast.iter_fields(value):
                child_mask, child_count = self.collect(item, next_depth)
                arg_read_mask |= child_mask
                node_count += child_count
            return self._record(value, arg_read_mask, node_count)
        if isinstance(value, list):
            arg_read_mask = 0
            node_count = 0
            for item in value:
                child_mask, child_count = self.collect(item, depth)
                arg_read_mask |= child_mask
                node_count += child_count
            return arg_read_mask, node_count
        return 0, 0

    def _name(self, node: ast.Name) -> _CollectResult:
        arg_read_mask = self.arg_masks.get(node.id, 0)
        if type(node.ctx) is ast.Load and self.current_statement_loads is not None:
            self.current_statement_loads.add(node.id)
        self._add_shape_token_triple(
            "Name",
            _name_role(node.id, self.args),
            type(node.ctx).__name__,
        )
        return self._record(
            node,
            arg_read_mask,
            2,
        )

    def _arg(self, node: ast.arg) -> _CollectResult:
        arg_read_mask = 0
        node_count = 1
        for item in (node.annotation, node.type_comment):
            child_mask, child_count = self.collect(item)
            arg_read_mask |= child_mask
            node_count += child_count
        return self._record(
            node,
            arg_read_mask,
            node_count,
        )

    def _record(
        self,
        node: ast.AST,
        arg_read_mask: int,
        node_count: int,
    ) -> _CollectResult:
        self.arg_read_masks[id(node)] = arg_read_mask
        return arg_read_mask, node_count

    def _record_node(self, node: ast.AST, depth: int) -> int:
        node_type = type(node)
        self._record_node_shape(node, node_type)
        next_depth = self._record_metrics(node_type, depth)
        self._record_structure(node, node_type)
        return next_depth

    def _add_shape_token(self, token: str) -> None:
        self.structure_hash = _hash_text(self.structure_hash, token)

    def _add_shape_token_pair(self, left: str, right: str) -> None:
        self.structure_hash = _hash_text(_hash_text(self.structure_hash, left), right)

    def _add_shape_token_triple(self, left: str, middle: str, right: str) -> None:
        self.structure_hash = _hash_text(
            _hash_text(_hash_text(self.structure_hash, left), middle),
            right,
        )

    def _record_node_shape(self, node: ast.AST, node_type: type[ast.AST]) -> None:
        if node_type is ast.Attribute:
            self._add_shape_token_pair(node_type.__name__, cast(ast.Attribute, node).attr)
        elif node_type is ast.arg:
            self._add_shape_token_pair(node_type.__name__, "_")
        elif node_type is ast.FunctionDef or node_type is ast.AsyncFunctionDef:
            self._add_shape_token_pair(node_type.__name__, "_")
        elif node_type is ast.Name:
            name = cast(ast.Name, node)
            self._add_shape_token_triple(
                node_type.__name__,
                _name_role(name.id, self.args),
                type(name.ctx).__name__,
            )
        else:
            self._add_shape_token(node_type.__name__)

    def _record_metrics(self, node_type: type[ast.AST], depth: int) -> int:
        if node_type in BRANCH_NODE_TYPES:
            self.branch_count += 1
        if node_type in LOOP_NODE_TYPES:
            self.loop_count += 1
        if node_type is ast.Return:
            self.return_count += 1
        next_depth = depth + 1 if node_type in NESTING_NODE_TYPES else depth
        self.max_nesting = max(self.max_nesting, next_depth)
        return next_depth

    def _record_structure(self, node: ast.AST, node_type: type[ast.AST]) -> None:
        if node_type is ast.Call:
            self.calls.append(cast(ast.Call, node))
        elif node_type is ast.Attribute:
            self.attributes.append(cast(ast.Attribute, node))
        elif node_type is ast.Return:
            self.returns.append(cast(ast.Return, node))
        elif node_type is ast.Assign:
            self.locals_.update(_target_names_many(cast(ast.Assign, node).targets))
        elif node_type is ast.AnnAssign:
            self.locals_.update(_target_names(cast(ast.AnnAssign, node).target))
        elif node_type is ast.With:
            self.controls.add("WITH")
            for item in cast(ast.With, node).items:
                if item.optional_vars:
                    self.locals_.update(_target_names(item.optional_vars))
        elif node_type in CONTROL_LOOP_NODE_TYPES:
            self.controls.add("LOOP")
        elif node_type in CONTROL_BRANCH_NODE_TYPES:
            self.controls.add("BRANCH")
        elif node_type is ast.Try:
            self.controls.add("TRY")


def _arg_roles(args: ast.arguments) -> dict[str, str]:
    ordered = [*args.posonlyargs, *args.args, *args.kwonlyargs]
    return {arg.arg: f"ARG{index}" for index, arg in enumerate(ordered)}


def _arg_masks(args: dict[str, str]) -> dict[str, int]:
    return {name: 1 << int(role[3:]) for name, role in args.items()}


def _name_role(name: str, args: dict[str, str]) -> str:
    return args.get(name, "_")


def _roles_from_mask(mask: int) -> tuple[str, ...]:
    return tuple(_iter_roles_from_mask(mask))


def _iter_roles_from_mask(mask: int) -> Iterable[str]:
    index = 0
    while mask:
        if mask & 1:
            yield f"ARG{index}"
        mask >>= 1
        index += 1


def _statement_sequence(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    context: _FeatureContext,
) -> list[str]:
    return [_statement_token(stmt, context) for stmt in node.body]


def _statement_token(stmt: ast.stmt, context: _FeatureContext) -> str:
    stmt_type = type(stmt)
    if stmt_type is ast.Expr and type(cast(ast.Expr, stmt).value) is ast.Call:
        return "CALL:" + context.call_token(cast(ast.Call, cast(ast.Expr, stmt).value))
    if stmt_type is ast.With:
        with_stmt = cast(ast.With, stmt)
        tokens = [
            context.call_token(item.context_expr)
            for item in with_stmt.items
            if type(item.context_expr) is ast.Call
        ]
        return "WITH:" + "|".join(tokens)
    if stmt_type is ast.Assign or stmt_type is ast.AnnAssign:
        return "ASSIGN:" + type(stmt).__name__
    if stmt_type is ast.Return:
        return "RETURN:" + ",".join(context.iter_arg_reads(cast(ast.Return, stmt).value))
    return type(stmt).__name__.upper()


def _call_facts(call: ast.Call, context: _FeatureContext) -> _CallFacts:
    callee = _callee_parts(call.func, context)
    namespace_tokens, name_tokens, call_kind, receiver_base, receiver_path = callee
    arg_roles = _call_arg_roles(call, context)
    kwarg_shape = _call_kwarg_shape(call, context)
    token = _call_token(callee, arg_roles, kwarg_shape)
    name = "_".join(name_tokens)
    callee_name = ".".join([*namespace_tokens, name]).strip(".") or name
    return _CallFacts(
        token=token,
        namespace_tokens=namespace_tokens,
        name_tokens=name_tokens,
        call_kind=call_kind,
        receiver_base=receiver_base,
        receiver_path=receiver_path,
        arg_roles=arg_roles,
        kwarg_shape=kwarg_shape,
        read_mask=context.arg_read_mask(call),
        callee_name=callee_name,
    )


def _call_token_for_call(call: ast.Call, context: _FeatureContext) -> str:
    return _call_token(
        _callee_parts(call.func, context),
        _call_arg_roles(call, context),
        _call_kwarg_shape(call, context),
    )


def _call_arg_roles(call: ast.Call, context: _FeatureContext) -> tuple[str, ...]:
    return tuple(_value_role(arg, context) for arg in call.args)


def _call_kwarg_shape(
    call: ast.Call,
    context: _FeatureContext,
) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            (str(keyword.arg), _value_role(keyword.value, context))
            for keyword in call.keywords
            if keyword.arg
        )
    )


def _call_fingerprint(facts: _CallFacts) -> CallFingerprint:
    return CallFingerprint(
        kind="CALL",
        token=facts.token,
        callee_shape=CalleeShape(
            namespace_tokens=facts.namespace_tokens,
            name_tokens=facts.name_tokens,
            call_kind=facts.call_kind,
        ),
        receiver_shape=(
            ExpressionShape(facts.receiver_base, facts.receiver_path)
            if facts.receiver_base
            else None
        ),
        arg_roles=facts.arg_roles,
        kwarg_shape=facts.kwarg_shape,
        reads=_roles_from_mask(facts.read_mask),
    )


def _normalization_transform_token(facts: _CallFacts) -> str:
    if facts.receiver_base != "ARG0" or facts.receiver_path:
        return ""
    name = "_".join(facts.name_tokens)
    if name not in NORMALIZATION_TRANSFORM_METHODS:
        return ""
    roles = (*facts.arg_roles, *(role for _, role in facts.kwarg_shape))
    if any(not role.startswith("CONST_") for role in roles):
        return ""
    return facts.token


def _callee_parts(
    node: ast.AST,
    context: _FeatureContext,
) -> _CalleeParts:
    node_type = type(node)
    if node_type is ast.Attribute:
        attribute = cast(ast.Attribute, node)
        receiver_base, receiver_path = _expr_parts(attribute.value, context)
        namespace_tokens: tuple[str, ...] = ()
        call_kind = "method"
        if type(attribute.value) is ast.Name:
            receiver = attribute.value
            if receiver.id not in context.args and receiver.id not in context.locals_:
                namespace_tokens = cached_identifier_tokens(receiver.id)
                call_kind = "function"
        return (
            tuple(namespace_tokens),
            cached_identifier_tokens(attribute.attr),
            call_kind,
            receiver_base,
            receiver_path,
        )
    if node_type is ast.Name:
        name = cast(ast.Name, node)
        return (
            (),
            cached_identifier_tokens(name.id),
            "function",
            "",
            (),
        )
    return (
        (),
        (type(node).__name__.lower(),),
        "unknown",
        "",
        (),
    )


def _call_token(
    callee: _CalleeParts,
    arg_roles: Sequence[str],
    kwarg_shape: Sequence[tuple[str, str]],
) -> str:
    namespace_tokens, name_tokens, _, receiver_base, receiver_path = callee
    namespace = ".".join(namespace_tokens)
    name = "_".join(name_tokens)
    access = ".".join(receiver_path)
    receiver_text = f"{receiver_base}.{access}".rstrip(".")
    target = ".".join(part for part in [namespace, receiver_text, name] if part)
    kwargs = ",".join(f"{key}:{value}" for key, value in kwarg_shape)
    return f"{target}(args={','.join(arg_roles)};kwargs={kwargs})"


def _parameter_use_vectors(
    context: _FeatureContext,
    call_facts: tuple[_CallFacts, ...],
) -> dict[str, ParameterUseVector]:
    vectors = {role: _MutableParameterUse() for role in context.args.values()}
    for attribute in context.attributes:
        shape = _expr_shape(attribute, context)
        if shape.base in vectors and shape.access_path:
            vectors[shape.base].access_paths.append(".".join(shape.access_path))
    for call, facts in zip(context.calls, call_facts, strict=True):
        _record_call_use(call, facts, context, vectors)
    for return_node in context.returns:
        for role in context.iter_arg_reads(return_node.value):
            vectors[role].returned = True
    return {role: _parameter_vector(vector) for role, vector in vectors.items()}


def _record_call_use(
    call: ast.Call,
    facts: _CallFacts,
    context: _FeatureContext,
    vectors: dict[str, _MutableParameterUse],
) -> None:
    name = "_".join(facts.name_tokens)
    if facts.receiver_base in vectors:
        path = ".".join([*facts.receiver_path, name]).strip(".")
        vectors[facts.receiver_base].receiver_of_calls.append(path)
    for index, arg in enumerate(call.args):
        for role in context.iter_arg_reads(arg):
            vectors[role].passed_as_argument_to.append(f"{facts.callee_name}.arg{index}")
    for keyword in call.keywords:
        if not keyword.arg:
            continue
        for role in context.iter_arg_reads(keyword.value):
            vectors[role].passed_as_argument_to.append(f"{facts.callee_name}.kwarg.{keyword.arg}")


def _parameter_vector(vector: _MutableParameterUse) -> ParameterUseVector:
    return ParameterUseVector(
        access_paths=_dedupe_strs(vector.access_paths),
        receiver_of_calls=_dedupe_strs(vector.receiver_of_calls),
        passed_as_argument_to=_dedupe_strs(vector.passed_as_argument_to),
        returned=vector.returned,
    )


def _parameter_features(
    context: _FeatureContext,
    call_facts: tuple[_CallFacts, ...],
) -> dict[str, frozenset[str]]:
    features: dict[str, set[str]] = {role: set() for role in context.args.values()}
    for attribute in context.attributes:
        shape = _expr_shape(attribute, context)
        if shape.base in features and shape.access_path:
            features[shape.base].add(f"access_paths:{'.'.join(shape.access_path)}")
    for call, facts in zip(context.calls, call_facts, strict=True):
        name = "_".join(facts.name_tokens)
        if facts.receiver_base in features:
            path = ".".join([*facts.receiver_path, name]).strip(".")
            features[facts.receiver_base].add(f"receiver_of_calls:{path}")
        for index, arg in enumerate(call.args):
            for role in context.iter_arg_reads(arg):
                features[role].add(f"passed_as_argument_to:{facts.callee_name}.arg{index}")
        for keyword in call.keywords:
            if not keyword.arg:
                continue
            for role in context.iter_arg_reads(keyword.value):
                features[role].add(f"passed_as_argument_to:{facts.callee_name}.kwarg.{keyword.arg}")
    returned = {role for item in context.returns for role in context.iter_arg_reads(item.value)}
    for role, values in features.items():
        values.add(f"returned:{role in returned}")
    return {role: frozenset(values) for role, values in features.items()}


def _literal_shapes(
    call_facts: tuple[_CallFacts, ...],
    defaults: dict[str, str],
) -> frozenset[str]:
    shapes = {value for value in defaults.values() if value.startswith("CONST_")}
    for facts in call_facts:
        shapes.update(value for value in facts.arg_roles if value.startswith("CONST_"))
        shapes.update(value for _, value in facts.kwarg_shape if value.startswith("CONST_"))
    return frozenset(shapes)


def _receiver_shapes(call_facts: tuple[_CallFacts, ...]) -> frozenset[str]:
    shapes: set[str] = set()
    for facts in call_facts:
        if not facts.receiver_base:
            continue
        access = ".".join(facts.receiver_path)
        if shape := f"{facts.receiver_base}.{access}".rstrip("."):
            shapes.add(shape)
    return frozenset(shapes)


def _dedupe_strs(value: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(set(value)))


def _expr_shape(node: ast.AST, context: _FeatureContext) -> ExpressionShape:
    base, access_path = _expr_parts(node, context)
    return ExpressionShape(base=base, access_path=access_path)


def _expr_parts(node: ast.AST, context: _FeatureContext) -> tuple[str, tuple[str, ...]]:
    access: list[str] = []
    current = node
    while type(current) is ast.Attribute:
        access.append(current.attr)
        current = current.value
    access.reverse()
    if type(current) is ast.Name:
        if current.id in context.args:
            return context.args[current.id], tuple(access)
        if current.id in context.locals_:
            return "LOCAL", tuple(access)
        return "CONTEXT", (current.id, *access)
    return type(current).__name__.upper(), tuple(access)


def _value_role(node: ast.AST, context: _FeatureContext) -> str:
    read_mask = context.arg_read_mask(node)
    if read_mask and read_mask & (read_mask - 1) == 0:
        return f"ARG{read_mask.bit_length() - 1}"
    if read_mask:
        return "ARG_MIXED"
    role = type(node).__name__.upper()
    node_type = type(node)
    if node_type is ast.Constant:
        role = _constant_shape(cast(ast.Constant, node).value)
    elif node_type is ast.Name and cast(ast.Name, node).id in context.locals_:
        role = "LOCAL"
    elif node_type is ast.Attribute and _expr_shape(node, context).base == "LOCAL":
        role = "LOCAL_ATTR"
    elif node_type is ast.Call:
        role = "CALL_RESULT"
    return role


def _constant_shape(value: object) -> str:
    if isinstance(value, bool):
        return "CONST_BOOL_TRUE" if value else "CONST_BOOL_FALSE"
    if isinstance(value, str):
        return "CONST_STR"
    if value is None:
        return "CONST_NONE"
    if isinstance(value, (int, float, complex)):
        return "CONST_NUM"
    return f"CONST_{type(value).__name__.upper()}"


def _local_dataflow_graph(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    context: _FeatureContext,
    sequence: list[str],
) -> DataflowGraph:
    nodes = [DataflowNode(id=role, label=role, kind="argument") for role in context.args.values()]
    edges: list[DataflowEdge] = []
    local_defs: dict[str, str] = {}
    for index, stmt in enumerate(node.body):
        stmt_id = f"STMT{index}"
        label = sequence[index] if index < len(sequence) else type(stmt).__name__.upper()
        sorted_arg_reads = context.arg_reads(stmt)
        sorted_local_reads = sorted(context.local_reads(stmt))
        sorted_local_writes = sorted(_local_writes(stmt))
        nodes.append(
            DataflowNode(
                id=stmt_id,
                label=label,
                kind="statement",
                arg_reads=tuple(sorted_arg_reads),
            )
        )
        edges.extend(
            DataflowEdge(role, stmt_id, "arg_read", role, label) for role in sorted_arg_reads
        )
        if index:
            previous = f"STMT{index - 1}"
            edges.append(
                DataflowEdge(previous, stmt_id, "lexical_order", sequence[index - 1], label)
            )
        for name in sorted_local_reads:
            if name in local_defs:
                edges.append(DataflowEdge(local_defs[name], stmt_id, "local_flow", name, label))
        for name in sorted_local_writes:
            local_defs[name] = stmt_id
    return DataflowGraph(nodes=tuple(nodes), edges=tuple(edges))


def _compact_graph_features(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    context: _FeatureContext,
    sequence: list[str],
) -> frozenset[str]:
    features = {f"node:argument:{role}" for role in context.args.values()}
    local_defs: dict[str, str] = {}
    for index, stmt in enumerate(node.body):
        label = sequence[index] if index < len(sequence) else type(stmt).__name__.upper()
        features.add(f"node:statement:{label}")
        for role in context.iter_arg_reads(stmt):
            features.add(f"edge:arg_read:{role}->{label}")
        if index:
            features.add(f"edge:lexical_order:{sequence[index - 1]}->{label}")
        for name in sorted(context.local_reads(stmt)):
            if name in local_defs:
                features.add(f"edge:local_flow:{name}->{label}")
        for name in sorted(_local_writes(stmt)):
            local_defs[name] = label
    return frozenset(features)


def _statement_arg_reads(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    context: _FeatureContext,
) -> tuple[tuple[int, tuple[str, ...]], ...]:
    return tuple(
        (index, reads) for index, stmt in enumerate(node.body) if (reads := context.arg_reads(stmt))
    )


def _local_writes(node: ast.AST) -> set[str]:
    return _target_names_many(_write_targets(node))


def _write_targets(node: ast.AST) -> tuple[ast.AST, ...]:
    node_type = type(node)
    if node_type is ast.Assign:
        return tuple(cast(ast.Assign, node).targets)
    if node_type is ast.AnnAssign:
        return (cast(ast.AnnAssign, node).target,)
    if node_type is ast.With:
        return tuple(
            item.optional_vars for item in cast(ast.With, node).items if item.optional_vars
        )
    return ()


def _target_names(node: ast.AST) -> set[str]:
    node_type = type(node)
    if node_type is ast.Name:
        return {cast(ast.Name, node).id}
    if node_type is ast.Tuple:
        return _target_names_many(cast(ast.Tuple, node).elts)
    if node_type is ast.List:
        return _target_names_many(cast(ast.List, node).elts)
    return set()


def _target_names_many(nodes: Iterable[ast.AST]) -> set[str]:
    return {name for node in nodes for name in _target_names(node)}


def _parameter_defaults(args: ast.arguments, arg_roles: dict[str, str]) -> dict[str, str]:
    positional = [*args.posonlyargs, *args.args]
    defaults = {
        arg.arg: default
        for arg, default in zip(positional[-len(args.defaults) :], args.defaults, strict=False)
    }
    defaults.update(
        {
            arg.arg: default
            for arg, default in zip(args.kwonlyargs, args.kw_defaults, strict=False)
            if default is not None
        }
    )
    return {
        arg_roles[name]: _constant_shape(default.value)
        if type(default) is ast.Constant
        else type(default).__name__.upper()
        for name, default in defaults.items()
        if name in arg_roles
    }


def _hash_text(value: int, text: str) -> int:
    return zlib.crc32(text.encode("utf-8"), value)


def _format_shape_hash(value: int) -> str:
    return f"shape32:{value:08x}"
