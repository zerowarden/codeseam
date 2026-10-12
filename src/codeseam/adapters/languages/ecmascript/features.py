from __future__ import annotations

from dataclasses import dataclass

from tree_sitter import Node

from codeseam.adapters.languages.ecmascript.body_shape import (
    body_statements,
    normalized_body_shape,
    parameter_roles,
)
from codeseam.adapters.languages.ecmascript.runtime import iter_named_nodes, node_text
from codeseam.adapters.languages.ecmascript.syntax_kinds import (
    ASSIGN_EXPRESSION_KINDS,
    CALL_TYPES,
    CONTROL_KINDS,
    DECLARATION_TYPES,
    STATEMENT_KINDS,
)
from codeseam.analysis import (
    DEFAULT_EXPRESSION,
    AssignKind,
    CalleeShape,
    CallFingerprint,
    DataflowEdge,
    DataflowGraph,
    DataflowNode,
    ExpressionShape,
    ParameterUseVector,
    ParamIR,
    StatementKind,
    assign_token,
    dataflow_graph_features,
    literal_shapes,
    normalization_transform_tokens,
    receiver_shapes,
    statement_arg_reads_from_graph,
    statement_token,
)
from codeseam.analysis.signatures.model import (
    OperationCompact,
    OperationFeatures,
    OperationFlow,
    empty_operation_features,
    parameter_vector_features,
)
from codeseam.platform import identifier_tokens

ASSIGN_TYPES = frozenset(
    {"assignment_expression", "lexical_declaration", "variable_declaration", "variable_declarator"}
)


@dataclass(frozen=True, slots=True)
class _ResolvedCallee:
    callee_shape: CalleeShape
    receiver_shape: ExpressionShape | None = None


def operation_features(
    source: bytes,
    body_node: Node | None,
    params: tuple[ParamIR, ...],
    *,
    include_relation_detail: bool = False,
) -> OperationFeatures:
    if body_node is None:
        return empty_operation_features()
    args = parameter_roles(params)
    locals_ = _local_names(source, body_node)
    calls = [_call_fingerprint(source, call, args, locals_) for call in _calls(body_node)]
    sequence = _statement_sequence(source, body_node, args, locals_)
    shape = normalized_body_shape(source, body_node, params)
    defaults = _parameter_defaults(params)
    if not include_relation_detail:
        return OperationFeatures(
            compact=OperationCompact(
                statement_sequence=tuple(sequence),
                call_tokens=tuple(call.token for call in calls),
                parameter_default_roles=tuple(sorted(defaults.items())),
                control_context_vector=tuple(_control_context_vector(body_node)),
                body_shape=shape.shape,
                body_shape_hash=shape.shape_hash,
                body_tree_node_count=shape.node_count,
                statement_keys=shape.statement_keys,
                statement_spans=shape.statement_spans,
            )
        )
    parameter_vectors = _parameter_use_vectors(source, body_node, args, locals_)
    graph = _local_dataflow_graph(
        source,
        body_node,
        args,
        locals_,
        sequence,
    )
    return OperationFeatures(
        compact=OperationCompact(
            statement_sequence=tuple(sequence),
            call_tokens=tuple(call.token for call in calls),
            parameter_default_roles=tuple(sorted(defaults.items())),
            normalization_transform_tokens=tuple(sorted(normalization_transform_tokens(calls))),
            graph_features=frozenset(dataflow_graph_features(graph)),
            literal_shapes=frozenset(literal_shapes(defaults, calls)),
            receiver_shapes=frozenset(receiver_shapes(calls)),
            parameter_features=tuple(
                sorted(
                    (role, frozenset(parameter_vector_features(vector)))
                    for role, vector in parameter_vectors.items()
                )
            ),
            statement_arg_reads=tuple(statement_arg_reads_from_graph(graph)),
            control_context_vector=tuple(_control_context_vector(body_node)),
            body_shape=shape.shape,
            body_shape_hash=shape.shape_hash,
            body_tree_node_count=shape.node_count,
            statement_keys=shape.statement_keys,
            statement_spans=shape.statement_spans,
        ),
        flow=OperationFlow(
            call_fingerprints=tuple(calls),
            parameter_use_vectors=tuple(sorted(parameter_vectors.items())),
            parameter_default_roles=tuple(sorted(defaults.items())),
            local_dataflow_graph=graph,
        ),
    )


def _local_names(source: bytes, node: Node) -> set[str]:
    names: set[str] = set()
    for child in iter_named_nodes(node):
        if child.type == "variable_declarator":
            if name := node_text(source, child.child_by_field_name("name")):
                names.add(name)
        elif child.type == "assignment_expression":
            names.update(_target_names(source, child.child_by_field_name("left")))
    return names


def _statement_sequence(
    source: bytes,
    body_node: Node,
    args: dict[str, str],
    locals_: set[str],
) -> list[str]:
    return [_statement_token(source, stmt, args, locals_) for stmt in body_statements(body_node)]


def _statement_token(
    source: bytes,
    stmt: Node,
    args: dict[str, str],
    locals_: set[str],
) -> str:
    """Map one top-level statement onto the shared `StatementKind` vocabulary.

    An arrow function's expression body returns its value, like a Python lambda.
    """

    if stmt.type == "return_statement" or not _is_statement(stmt):
        reads = ",".join(sorted(_arg_reads(source, stmt, args)))
        return statement_token(StatementKind.RETURN, reads)
    if stmt.type in DECLARATION_TYPES:
        return assign_token(AssignKind.BIND)
    expression = _statement_expression(stmt)
    if expression is not None and expression.type in CALL_TYPES:
        call = _call_fingerprint(source, expression, args, locals_)
        return statement_token(StatementKind.CALL, call.token)
    if expression is not None and (assign := ASSIGN_EXPRESSION_KINDS.get(expression.type)):
        return assign_token(assign)
    return statement_token(STATEMENT_KINDS.get(stmt.type, StatementKind.OTHER))


def _is_statement(node: Node) -> bool:
    return node.type in STATEMENT_KINDS or node.type.endswith(("_statement", "_declaration"))


def _statement_expression(stmt: Node) -> Node | None:
    """The expression of an expression statement, looking through `await`."""

    if stmt.type != "expression_statement" or not stmt.named_children:
        return None
    expression = stmt.named_children[0]
    if expression.type == "await_expression" and expression.named_children:
        return expression.named_children[0]
    return expression


def _call_fingerprint(
    source: bytes,
    call: Node,
    args: dict[str, str],
    locals_: set[str],
) -> CallFingerprint:
    callee = _callee_shape(source, call.child_by_field_name("function"), args, locals_)
    arg_roles = [_value_role(source, arg, args, locals_) for arg in _call_arguments(call)]
    reads = sorted(_arg_reads(source, call, args))
    return CallFingerprint(
        kind="CALL",
        token=_call_token(callee, arg_roles, {}),
        callee_shape=callee.callee_shape,
        receiver_shape=callee.receiver_shape,
        arg_roles=tuple(arg_roles),
        kwarg_shape=(),
        reads=tuple(reads),
    )


def _callee_shape(
    source: bytes,
    node: Node | None,
    args: dict[str, str],
    locals_: set[str],
) -> _ResolvedCallee:
    if node is None:
        return _unknown_callee()
    if node.type == "member_expression":
        receiver = _expr_shape(source, node.child_by_field_name("object"), args, locals_)
        property_name = node_text(source, node.child_by_field_name("property")) or "unknown"
        namespace_tokens: tuple[str, ...] = ()
        call_kind = "method"
        if receiver.base == "CONTEXT" and receiver.access_path:
            namespace_tokens = tuple(identifier_tokens(receiver.access_path[0]))
            call_kind = "function"
        return _ResolvedCallee(
            callee_shape=CalleeShape(
                namespace_tokens=namespace_tokens,
                name_tokens=tuple(identifier_tokens(property_name)),
                call_kind=call_kind,
            ),
            receiver_shape=receiver,
        )
    if node.type == "identifier":
        name = node_text(source, node) or "unknown"
        return _ResolvedCallee(
            callee_shape=CalleeShape(
                name_tokens=tuple(identifier_tokens(name)),
                call_kind="function",
            )
        )
    return _ResolvedCallee(callee_shape=CalleeShape(name_tokens=(node.type,)))


def _unknown_callee() -> _ResolvedCallee:
    return _ResolvedCallee(callee_shape=CalleeShape(name_tokens=("unknown",)))


def _call_arguments(call: Node) -> list[Node]:
    arguments = call.child_by_field_name("arguments")
    return list(arguments.named_children) if arguments is not None else []


def _call_token(
    callee: _ResolvedCallee,
    arg_roles: list[str],
    kwarg_shape: dict[str, str],
) -> str:
    namespace = ".".join(callee.callee_shape.namespace_tokens)
    name = "_".join(callee.callee_shape.name_tokens)
    receiver = callee.receiver_shape
    base = receiver.base if receiver is not None else ""
    access = ".".join(receiver.access_path) if receiver is not None else ""
    receiver_text = f"{base}.{access}".rstrip(".")
    target = ".".join(part for part in [namespace, receiver_text, name] if part)
    kwargs = ",".join(f"{key}:{value}" for key, value in sorted(kwarg_shape.items()))
    return f"{target}(args={','.join(arg_roles)};kwargs={kwargs})"


def _parameter_use_vectors(
    source: bytes,
    node: Node,
    args: dict[str, str],
    locals_: set[str],
) -> dict[str, ParameterUseVector]:
    vectors: dict[str, dict[str, object]] = {
        role: {
            "access_paths": set[str](),
            "receiver_of_calls": set[str](),
            "passed_as_argument_to": set[str](),
            "returned": False,
        }
        for role in args.values()
    }
    for child in iter_named_nodes(node):
        if child.type == "member_expression":
            shape = _expr_shape(source, child, args, locals_)
            if shape.base in vectors and shape.access_path:
                _add_vector_value(vectors[shape.base], "access_paths", ".".join(shape.access_path))
        elif child.type in CALL_TYPES:
            _record_call_use(source, child, args, locals_, vectors)
        elif child.type == "return_statement":
            for role in _arg_reads(source, child, args):
                vectors[role]["returned"] = True
    return {role: _parameter_vector(vector) for role, vector in vectors.items()}


def _record_call_use(
    source: bytes,
    call: Node,
    args: dict[str, str],
    locals_: set[str],
    vectors: dict[str, dict[str, object]],
) -> None:
    callee = _callee_shape(source, call.child_by_field_name("function"), args, locals_)
    receiver = callee.receiver_shape
    name = "_".join(callee.callee_shape.name_tokens)
    if receiver is not None and receiver.base in vectors:
        path = ".".join([*receiver.access_path, name]).strip(".")
        _add_vector_value(vectors[receiver.base], "receiver_of_calls", path)
    callee_name = ".".join([*callee.callee_shape.namespace_tokens, name]).strip(".") or name
    for index, arg in enumerate(_call_arguments(call)):
        for role in _arg_reads(source, arg, args):
            _add_vector_value(vectors[role], "passed_as_argument_to", f"{callee_name}.arg{index}")


def _add_vector_value(vector: dict[str, object], key: str, value: str) -> None:
    values = vector.get(key)
    if isinstance(values, set):
        values.add(value)


def _parameter_vector(vector: dict[str, object]) -> ParameterUseVector:
    return ParameterUseVector(
        access_paths=tuple(sorted(_str_set(vector.get("access_paths")))),
        receiver_of_calls=tuple(sorted(_str_set(vector.get("receiver_of_calls")))),
        passed_as_argument_to=tuple(sorted(_str_set(vector.get("passed_as_argument_to")))),
        returned=bool(vector.get("returned")),
    )


def _str_set(value: object) -> set[str]:
    if not isinstance(value, set):
        return set()
    return {str(item) for item in value}


def _expr_shape(  # noqa: PLR0911
    source: bytes,
    node: Node | None,
    args: dict[str, str],
    locals_: set[str],
) -> ExpressionShape:
    if node is None:
        return ExpressionShape(base="UNKNOWN")
    if node.type == "member_expression":
        base = _expr_shape(source, node.child_by_field_name("object"), args, locals_)
        property_name = node_text(source, node.child_by_field_name("property"))
        if property_name:
            return ExpressionShape(
                base=base.base,
                access_path=(*base.access_path, property_name),
            )
        return base
    if node.type == "identifier":
        name = node_text(source, node) or ""
        if name in args:
            return ExpressionShape(base=args[name])
        if name in locals_:
            return ExpressionShape(base="LOCAL")
        return ExpressionShape(base="CONTEXT", access_path=(name,) if name else ())
    return ExpressionShape(base=node.type.upper())


def _value_role(  # noqa: PLR0911
    source: bytes,
    node: Node,
    args: dict[str, str],
    locals_: set[str],
) -> str:
    reads = _arg_reads(source, node, args)
    if len(reads) == 1:
        return next(iter(reads))
    if reads:
        return "ARG_MIXED"
    if node.type in {"string", "template_string"}:
        return "CONST_STR"
    if node.type in {"number", "unary_expression"}:
        return "CONST_NUM"
    if node.type == "true":
        return "CONST_BOOL_TRUE"
    if node.type == "false":
        return "CONST_BOOL_FALSE"
    if node.type in {"null", "undefined"}:
        return "CONST_NONE"
    if node.type == "identifier" and (node_text(source, node) or "") in locals_:
        return "LOCAL"
    if (
        node.type == "member_expression"
        and _expr_shape(source, node, args, locals_).base == "LOCAL"
    ):
        return "LOCAL_ATTR"
    if node.type in CALL_TYPES:
        return "CALL_RESULT"
    return node.type.upper()


def _arg_reads(source: bytes, node: Node | None, args: dict[str, str]) -> set[str]:
    if node is None:
        return set()
    return {
        args[text]
        for child in iter_named_nodes(node)
        if child.type == "identifier"
        and (text := node_text(source, child)) is not None
        and text in args
    }


def _local_dataflow_graph(
    source: bytes,
    node: Node,
    args: dict[str, str],
    locals_: set[str],
    sequence: list[str],
) -> DataflowGraph:
    nodes = [DataflowNode(id=role, label=role, kind="argument") for role in args.values()]
    edges: list[DataflowEdge] = []
    local_defs: dict[str, str] = {}
    statements = body_statements(node)
    for index, stmt in enumerate(statements):
        stmt_id = f"STMT{index}"
        label = sequence[index] if index < len(sequence) else stmt.type.upper()
        nodes.append(
            DataflowNode(
                id=stmt_id,
                label=label,
                kind="statement",
                arg_reads=tuple(sorted(_arg_reads(source, stmt, args))),
            )
        )
        edges.extend(
            DataflowEdge(
                kind="arg_read",
                from_label=role,
                to_label=label,
            )
            for role in sorted(_arg_reads(source, stmt, args))
        )
        if index:
            edges.append(
                DataflowEdge(
                    kind="lexical_order",
                    from_label=sequence[index - 1],
                    to_label=label,
                )
            )
        for name in sorted(_local_reads(source, stmt, locals_)):
            if name in local_defs:
                edges.append(
                    DataflowEdge(
                        kind="local_flow",
                        from_label=name,
                        to_label=label,
                    )
                )
        for name in sorted(_local_writes(source, stmt)):
            local_defs[name] = stmt_id
    return DataflowGraph(nodes=tuple(nodes), edges=tuple(edges))


def _local_reads(source: bytes, node: Node, locals_: set[str]) -> set[str]:
    return {
        text
        for child in iter_named_nodes(node)
        if child.type == "identifier"
        and (text := node_text(source, child)) is not None
        and text in locals_
    }


def _local_writes(source: bytes, node: Node) -> set[str]:
    if node.type in ASSIGN_TYPES:
        return _target_names(source, node.child_by_field_name("left")) | _target_names(
            source,
            node.child_by_field_name("name"),
        )
    return {
        name
        for child in iter_named_nodes(node)
        if child.type == "variable_declarator"
        for name in _target_names(source, child.child_by_field_name("name"))
    }


def _calls(node: Node) -> list[Node]:
    return [child for child in iter_named_nodes(node) if child.type in CALL_TYPES]


def _target_names(source: bytes, node: Node | None) -> set[str]:
    if node is None:
        return set()
    if node.type == "identifier":
        text = node_text(source, node)
        return {text} if text else set()
    return {
        text
        for child in iter_named_nodes(node)
        if child.type == "identifier" and (text := node_text(source, child)) is not None
    }


def _parameter_defaults(params: tuple[ParamIR, ...]) -> dict[str, str]:
    return {
        f"ARG{index}": param.default_role for index, param in enumerate(params) if param.has_default
    }


NONE_ROLE = "CONST_NONE"


def default_value_role(source: bytes, node: Node | None) -> str:
    """A literal default's `CONST_*` role, else `DEFAULT_EXPRESSION`, as in Python."""

    if node is None:
        return DEFAULT_EXPRESSION
    role = _value_role(source, node, {}, set())
    return role if role.startswith("CONST_") else DEFAULT_EXPRESSION


def _control_context_vector(node: Node) -> list[str]:
    kinds = {
        CONTROL_KINDS[child.type] for child in iter_named_nodes(node) if child.type in CONTROL_KINDS
    }
    return sorted(kind.value for kind in kinds)
