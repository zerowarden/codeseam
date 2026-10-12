from __future__ import annotations

import ast
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from hashlib import blake2b
from typing import cast

from codeseam.analysis import (
    DEFAULT_EXPRESSION,
    NORMALIZATION_TRANSFORM_METHODS,
    AssignKind,
    ControlKind,
    ExpressionShape,
    OrderedTree,
    StatementKind,
    assign_token,
    statement_token,
)
from codeseam.analysis.signatures import MAX_TREE_DEPTH
from codeseam.analysis.signatures.model import OperationCompact, OperationFeatures, OperationFlow
from codeseam.platform import cached_identifier_tokens

type _CollectResult = tuple[int, int]
type _CalleeParts = tuple[tuple[str, ...], tuple[str, ...], str, str, tuple[str, ...]]

# ECMAScript counterparts are in `ecmascript/syntax_kinds.py`; keep the two in step.
BRANCH_NODES = (ast.If, ast.IfExp, ast.match_case, ast.ExceptHandler)
LOOP_NODES = (ast.For, ast.AsyncFor, ast.While, ast.comprehension)
NESTING_NODES = (
    ast.If,
    ast.Match,
    ast.Try,
    ast.TryStar,
    ast.With,
    ast.AsyncWith,
    ast.For,
    ast.AsyncFor,
    ast.While,
)
BRANCH_NODE_TYPES = frozenset(BRANCH_NODES)
LOOP_NODE_TYPES = frozenset(LOOP_NODES)
NESTING_NODE_TYPES = frozenset(NESTING_NODES)
CONTROL_KINDS: dict[type[ast.AST], ControlKind] = {
    ast.If: ControlKind.BRANCH,
    ast.Match: ControlKind.BRANCH,
    ast.For: ControlKind.LOOP,
    ast.AsyncFor: ControlKind.LOOP,
    ast.While: ControlKind.LOOP,
    ast.Try: ControlKind.TRY,
    ast.TryStar: ControlKind.TRY,
    ast.ExceptHandler: ControlKind.CATCH,
    ast.With: ControlKind.WITH,
    ast.AsyncWith: ControlKind.WITH,
    ast.Await: ControlKind.AWAIT,
}
BINDING_NODE_TYPES = frozenset(
    (
        ast.FunctionDef,
        ast.AsyncFunctionDef,
        ast.ClassDef,
        ast.ExceptHandler,
        ast.MatchAs,
        ast.MatchStar,
        ast.MatchMapping,
        ast.Import,
        ast.ImportFrom,
        ast.Global,
        ast.Nonlocal,
    )
)
STATEMENT_KEY_BYTES = 8
OPERATOR_NODE_TYPES = (ast.operator, ast.boolop, ast.cmpop, ast.unaryop)
CONSTANT_LABEL_LIMIT = 48


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


def operation_features(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    include_relation_detail: bool = False,
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
    call_facts = (
        tuple(context.call_facts(call) for call in context.calls) if include_relation_detail else ()
    )
    call_tokens = (
        tuple(facts.token for facts in call_facts)
        if include_relation_detail
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
            statement_keys=context.statement_keys,
            statement_spans=tuple(
                (stmt.lineno, stmt.end_lineno or stmt.lineno) for stmt in node.body
            ),
            body_tree=_body_tree(node, context.name_roles) if include_relation_detail else None,
            branch_count=context.branch_count,
            loop_count=context.loop_count,
            return_count=context.return_count,
            max_nesting=context.max_nesting,
        ),
        flow=OperationFlow(parameter_default_roles=tuple(sorted(defaults.items()))),
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
    statement_keys: tuple[str, ...]
    name_roles: dict[str, str]
    branch_count: int
    loop_count: int
    return_count: int
    max_nesting: int
    _arg_read_masks: dict[int, int] = field(default_factory=dict)
    _load_reads: dict[int, set[str]] = field(default_factory=dict)
    _call_tokens: dict[int, str] = field(default_factory=dict)
    _call_facts: dict[int, _CallFacts] = field(default_factory=dict)

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
            statement_keys=collector.statement_keys(),
            name_roles=collector.name_roles(),
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

    def call_token(self, call: ast.Call) -> str:
        key = id(call)
        token = self._call_tokens.get(key)
        if token is None:
            token = _call_token_for_call(call, self)
            self._call_tokens[key] = token
        return token


@dataclass(frozen=True, slots=True)
class _Visit:
    value: object
    depth: int


@dataclass(frozen=True, slots=True)
class _Exit:
    node: ast.AST | None  # None for a field list, which records nothing
    child_count: int
    base_count: int


@dataclass(frozen=True, slots=True)
class _CalleeSlot:
    pass


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
    shape_tokens: list[str] = field(default_factory=list)
    name_slots: list[tuple[int, str]] = field(default_factory=list)
    bound_names: set[str] = field(default_factory=set)
    outer_names: set[str] = field(default_factory=set)
    statement_spans: list[tuple[int, int]] = field(default_factory=list)
    literal_slots: list[int] = field(default_factory=list)
    callee_slots: set[int] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.arg_masks = _arg_masks(self.args)

    def collect_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> tuple[str, int]:
        self.bound_names.add(node.name)  # renamed recursive clones still match
        body_node_count = 1
        for child in node.body:
            previous_loads = self.current_statement_loads
            # Local-flow features only query reads at top-level statement
            # boundaries. Keep one mutable read set per statement instead of
            # allocating and unioning a set for every AST node in the subtree.
            statement_loads: set[str] = set()
            self.current_statement_loads = statement_loads
            start = len(self.shape_tokens)
            try:
                item = self.collect(child)
            finally:
                self.current_statement_loads = previous_loads
            self.statement_spans.append((start, len(self.shape_tokens)))
            self.load_reads[id(child)] = statement_loads
            body_node_count += item[1]
        return self._shape_hash(), body_node_count

    def name_roles(self) -> dict[str, str]:
        """Parameter role, LOCALn in order of first use, or FREE:name for each name."""

        local_names = self.bound_names - self.outer_names
        roles: dict[str, str] = {}
        local_count = 0
        for _, name in self.name_slots:
            if name in roles:
                continue
            if role := self.args.get(name):
                roles[name] = role
            elif name in local_names:
                roles[name] = f"LOCAL{local_count}"
                local_count += 1
            else:
                roles[name] = f"FREE:{name}"
        return roles

    def statement_keys(self) -> tuple[str, ...]:
        """Type-2 digest per top-level statement, once `_shape_hash` resolved names.

        Literal values and free names outside call position are abstracted, so
        statements that differ only in data (`User` vs `Order`, `"users"` vs
        `"orders"`) align; structure, operators, attributes and callees still
        tell statements apart. Exact values stay in the body hash and tree.
        """

        tokens = self.shape_tokens
        abstract = set(self.literal_slots) | {
            index
            for index, _ in self.name_slots
            if index not in self.callee_slots and tokens[index].startswith("FREE:")
        }
        return tuple(
            blake2b(
                "\x1f".join(
                    "_" if index in abstract else tokens[index] for index in range(start, end)
                ).encode("utf-8", "surrogatepass"),
                digest_size=STATEMENT_KEY_BYTES,
            ).hexdigest()
            for start, end in self.statement_spans
        )

    def _shape_hash(self) -> str:
        """Hash shape tokens once every binding in the function is known.

        Parameters and locals are renamed consistently so renamed clones still
        hash together; free names (callees, modules, builtins) keep their
        identity so `read_json(x)` and `delete_all(x)` do not. Roles are resolved
        here because the walk can meet a use before its binding (comprehension
        elements precede their targets).
        """
        roles = self.name_roles()
        for index, name in self.name_slots:
            self.shape_tokens[index] = roles[name]
        # The separator keeps token boundaries unambiguous ("ab"+"c" != "a"+"bc").
        payload = "\x1f".join(self.shape_tokens).encode("utf-8", "surrogatepass")
        return f"shape128:{blake2b(payload, digest_size=16).hexdigest()}"

    def collect(self, value: object, depth: int = 0) -> _CollectResult:
        """Walk one subtree iteratively; nesting depth is unbounded in real code.

        Shape tokens are emitted in pre-order and each node's arg-read mask and
        node count are aggregated in post-order, exactly as a recursive walk would.
        """

        results: list[_CollectResult] = []
        work: list[_Visit | _Exit | _CalleeSlot] = [_Visit(value, depth)]
        while work:
            step = work.pop()
            if type(step) is _CalleeSlot:
                self.callee_slots.add(len(self.shape_tokens) + 1)  # the next Name's slot
            elif type(step) is _Exit:
                exit_step = step
                children = results[len(results) - exit_step.child_count :]
                del results[len(results) - exit_step.child_count :]
                mask, count = 0, exit_step.base_count
                for child_mask, child_count in children:
                    mask |= child_mask
                    count += child_count
                if exit_step.node is not None:
                    self._record(exit_step.node, mask, count)
                results.append((mask, count))
            else:
                visit = cast(_Visit, step)
                if (leaf := self._leaf(visit.value)) is not None:
                    results.append(leaf)
                else:
                    work.extend(self._expand(visit.value, visit.depth))
        return results[-1]

    def _leaf(self, value: object) -> _CollectResult | None:
        value_type = type(value)
        if value_type is ast.Name:
            return self._name(cast(ast.Name, value))
        if value_type is ast.Constant:
            constant = cast(ast.Constant, value)
            self._add_shape_token_triple(
                "Constant",
                type(constant.value).__name__,
                repr(constant.value),
            )
            self.literal_slots.append(len(self.shape_tokens) - 1)
            return self._record(constant, 0, 1)
        if value_type is ast.arg or isinstance(value, ast.AST | list):
            return None
        return 0, 0

    def _expand(self, value: object, depth: int) -> list[_Visit | _Exit | _CalleeSlot]:
        """Steps in stack order (last item runs first) for a node with children."""

        if type(value) is ast.arg:
            arg = value
            self.bound_names.add(arg.arg)
            items: list[object] = [arg.annotation, arg.type_comment]
            return [_Exit(arg, len(items), 1), *(_Visit(item, 0) for item in reversed(items))]
        if isinstance(value, list):
            return [_Exit(None, len(value), 0), *(_Visit(item, depth) for item in reversed(value))]
        node = cast(ast.AST, value)
        next_depth = self._record_node(node, depth)
        fields = list(ast.iter_fields(node))
        steps: list[_Visit | _Exit | _CalleeSlot] = [_Exit(node, len(fields), 1)]
        for field_name, item in reversed(fields):
            steps.append(_Visit(item, next_depth))
            if type(node) is ast.Call and field_name == "func" and type(item) is ast.Name:
                steps.append(_CalleeSlot())
        return steps

    def _name(self, node: ast.Name) -> _CollectResult:
        arg_read_mask = self.arg_masks.get(node.id, 0)
        if type(node.ctx) is ast.Load and self.current_statement_loads is not None:
            self.current_statement_loads.add(node.id)
        if type(node.ctx) is not ast.Load:
            self.bound_names.add(node.id)
        self.shape_tokens.append("Name")
        self.name_slots.append((len(self.shape_tokens), node.id))
        self.shape_tokens.extend(("", type(node.ctx).__name__))
        return self._record(
            node,
            arg_read_mask,
            2,
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
        self.shape_tokens.append(token)

    def _add_shape_token_pair(self, left: str, right: str) -> None:
        self.shape_tokens.extend((left, right))

    def _add_shape_token_triple(self, left: str, middle: str, right: str) -> None:
        self.shape_tokens.extend((left, middle, right))

    def _record_node_shape(self, node: ast.AST, node_type: type[ast.AST]) -> None:
        if node_type is ast.Attribute:
            self._add_shape_token_pair(node_type.__name__, cast(ast.Attribute, node).attr)
        elif node_type is ast.keyword:
            self._add_shape_token_pair(node_type.__name__, cast(ast.keyword, node).arg or "**")
        elif node_type is ast.FunctionDef or node_type is ast.AsyncFunctionDef:
            self._add_shape_token_pair(node_type.__name__, "_")
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
        if node_type in BINDING_NODE_TYPES:
            self._record_binding(node)
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
        elif isinstance(node, ast.With | ast.AsyncWith):
            for item in node.items:
                if item.optional_vars:
                    self.locals_.update(_target_names(item.optional_vars))
        if control := CONTROL_KINDS.get(node_type):
            self.controls.add(control.value)

    def _record_binding(self, node: ast.AST) -> None:
        if isinstance(node, ast.Global | ast.Nonlocal):
            self.outer_names.update(node.names)
        elif isinstance(node, ast.Import | ast.ImportFrom):
            self.bound_names.update(
                (alias.asname or alias.name).split(".")[0] for alias in node.names
            )
        elif name := getattr(node, "rest" if type(node) is ast.MatchMapping else "name", None):
            self.bound_names.add(name)


def body_tree(node: ast.FunctionDef | ast.AsyncFunctionDef) -> OrderedTree | None:
    """Normalized body tree for tree-edit distance, labelled like the body hash.

    Names become parameter/local roles or `FREE:name`; operators become `op:`
    leaves so operator changes stay visible; expression contexts are dropped.
    Relation-detail extraction builds the same tree from its own name roles. None
    when the body nests deeper than `MAX_TREE_DEPTH`.
    """

    return operation_features(node, include_relation_detail=True).compact.body_tree


def _body_tree(
    node: ast.FunctionDef | ast.AsyncFunctionDef, roles: dict[str, str]
) -> OrderedTree | None:
    statements = [_tree(child, roles) for child in node.body]
    if any(statement is None for statement in statements):
        return None
    return OrderedTree("body", tuple(statement for statement in statements if statement))


def _tree(node: ast.AST, roles: dict[str, str]) -> OrderedTree | None:
    """Iterative post-order build of one statement's tree; None past `MAX_TREE_DEPTH`."""

    # Results stack, not an id() map: CPython shares operator nodes such as ast.Add().
    results: list[OrderedTree] = []
    stack: list[tuple[ast.AST, int, bool]] = [(node, 0, False)]
    while stack:
        current, depth, expanded = stack.pop()
        if depth > MAX_TREE_DEPTH:
            return None
        children = _tree_children(current)
        if not expanded and children:
            stack.append((current, depth, True))
            stack.extend((child, depth + 1, False) for child in reversed(children))
            continue
        first = len(results) - len(children)
        items = tuple(results[first:])
        del results[first:]
        results.append(OrderedTree(_tree_label(current, roles), items))
    return results[-1]


def _tree_children(node: ast.AST) -> list[ast.AST]:
    if type(node) in {ast.Name, ast.Constant} or isinstance(node, OPERATOR_NODE_TYPES):
        return []
    children: list[ast.AST] = []
    for _, value in ast.iter_fields(node):
        items = value if isinstance(value, list) else [value]
        children.extend(
            item
            for item in items
            if isinstance(item, ast.AST) and not isinstance(item, ast.expr_context)
        )
    return children


def _tree_label(node: ast.AST, roles: dict[str, str]) -> str:
    node_type = type(node)
    if node_type is ast.Name:
        name = cast(ast.Name, node).id
        return f"Name:{roles.get(name, f'FREE:{name}')}"
    if node_type is ast.Constant:
        return _constant_label(cast(ast.Constant, node).value)
    if isinstance(node, OPERATOR_NODE_TYPES):
        return f"op:{node_type.__name__}"
    if node_type is ast.Attribute:
        return f"Attribute:{cast(ast.Attribute, node).attr}"
    if node_type is ast.keyword:
        return f"keyword:{cast(ast.keyword, node).arg or '**'}"
    return node_type.__name__


def _constant_label(value: object) -> str:
    text = repr(value)
    if len(text) > CONSTANT_LABEL_LIMIT:
        digest = blake2b(text.encode("utf-8", "surrogatepass"), digest_size=4).hexdigest()
        text = f"{text[: CONSTANT_LABEL_LIMIT // 2]}#{digest}"
    return f"Constant:{type(value).__name__}:{text}"


def _arg_roles(args: ast.arguments) -> dict[str, str]:
    """Parameter roles in call order, `*args` and `**kwargs` included, as in the shape."""

    ordered = [*args.posonlyargs, *args.args, args.vararg, *args.kwonlyargs, args.kwarg]
    return {arg.arg: f"ARG{index}" for index, arg in enumerate(item for item in ordered if item)}


def _arg_masks(args: dict[str, str]) -> dict[str, int]:
    return {name: 1 << int(role[3:]) for name, role in args.items()}


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


ASSIGN_KINDS: dict[type[ast.stmt], AssignKind] = {
    ast.Assign: AssignKind.BIND,
    ast.AnnAssign: AssignKind.BIND,
    ast.AugAssign: AssignKind.UPDATE,
}
STATEMENT_KINDS: dict[type[ast.stmt], StatementKind] = {
    ast.AnnAssign: StatementKind.DECLARE,
    ast.If: StatementKind.IF,
    ast.Match: StatementKind.SWITCH,
    ast.For: StatementKind.LOOP,
    ast.AsyncFor: StatementKind.LOOP,
    ast.While: StatementKind.LOOP,
    ast.Try: StatementKind.TRY,
    ast.TryStar: StatementKind.TRY,
    ast.Raise: StatementKind.RAISE,
    ast.FunctionDef: StatementKind.DEFINE,
    ast.AsyncFunctionDef: StatementKind.DEFINE,
    ast.ClassDef: StatementKind.DEFINE,
    ast.Break: StatementKind.BREAK,
    ast.Continue: StatementKind.CONTINUE,
    ast.Pass: StatementKind.PASS,
    ast.Assert: StatementKind.ASSERT,
    ast.Delete: StatementKind.DELETE,
    ast.Import: StatementKind.IMPORT,
    ast.ImportFrom: StatementKind.IMPORT,
    ast.Global: StatementKind.DECLARE,
    ast.Nonlocal: StatementKind.DECLARE,
    ast.Expr: StatementKind.EXPR,
}


def _statement_token(stmt: ast.stmt, context: _FeatureContext) -> str:
    """Map one top-level statement onto the shared `StatementKind` vocabulary."""

    if isinstance(stmt, ast.Expr) and (call := _statement_call(stmt.value)):
        return statement_token(StatementKind.CALL, context.call_token(call))
    if isinstance(stmt, ast.With | ast.AsyncWith):
        calls = (item.context_expr for item in stmt.items)
        tokens = (context.call_token(call) for call in calls if isinstance(call, ast.Call))
        return statement_token(StatementKind.WITH, "|".join(tokens))
    assign = ASSIGN_KINDS.get(type(stmt))
    if assign and not (isinstance(stmt, ast.AnnAssign) and stmt.value is None):
        return assign_token(assign)
    if isinstance(stmt, ast.Return):
        return statement_token(
            StatementKind.RETURN, ",".join(sorted(context.iter_arg_reads(stmt.value)))
        )
    return statement_token(STATEMENT_KINDS.get(type(stmt), StatementKind.OTHER))


def _statement_call(value: ast.expr) -> ast.Call | None:
    if isinstance(value, ast.Await):
        value = value.value
    return value if isinstance(value, ast.Call) else None


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
    for item in context.returns:
        for role in context.iter_arg_reads(item.value):
            features[role].add("returned")
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
        arg_roles[name]: _default_role(default)
        for name, default in defaults.items()
        if name in arg_roles
    }


def _default_role(default: ast.expr) -> str:
    """A literal default's `CONST_*` role, else `DEFAULT_EXPRESSION`, as in ECMAScript."""

    if isinstance(default, ast.UnaryOp) and isinstance(default.op, ast.USub | ast.UAdd):
        default = default.operand
    if isinstance(default, ast.Constant):
        return _constant_shape(default.value)
    return DEFAULT_EXPRESSION
