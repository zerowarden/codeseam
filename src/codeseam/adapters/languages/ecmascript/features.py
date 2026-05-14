from __future__ import annotations

import re
from dataclasses import dataclass

from tree_sitter import Node

from codeseam.adapters.languages.ecmascript.body_shape import normalized_body_shape, parameter_roles
from codeseam.adapters.languages.ecmascript.runtime import iter_named_nodes, node_text
from codeseam.analysis import (
    CalleeShape,
    CallFingerprint,
    DataflowEdge,
    DataflowGraph,
    DataflowNode,
    ExpressionShape,
    OperationCompact,
    OperationFeatures,
    OperationFlow,
    ParameterUseVector,
    ParamIR,
    call_kwarg_shape_values,
)
from codeseam.platform import identifier_tokens

CALL_TYPES = frozenset({"call_expression", "new_expression"})
BRANCH_TYPES = frozenset({"if_statement", "switch_statement", "conditional_expression"})
LOOP_TYPES = frozenset({"for_statement", "for_in_statement", "while_statement", "do_statement"})
TRY_TYPES = frozenset({"try_statement"})
CATCH_TYPES = frozenset({"catch_clause"})
ASSIGN_TYPES = frozenset(
    {"assignment_expression", "lexical_declaration", "variable_declaration", "variable_declarator"}
)
_STMT_ID_RE = re.compile(r"^STMT(?P<index>\d+)$")


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
        return _empty_features()
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
            normalization_transform_tokens=tuple(sorted(_normalization_transform_tokens(calls))),
            graph_features=frozenset(_graph_features(graph)),
            literal_shapes=frozenset(_literal_shapes(defaults, calls)),
            receiver_shapes=frozenset(_receiver_shapes(calls)),
            parameter_features=tuple(
                sorted(
                    (role, frozenset(_parameter_vector_features(vector)))
                    for role, vector in parameter_vectors.items()
                )
            ),
            statement_arg_reads=_statement_arg_reads(graph),
            control_context_vector=tuple(_control_context_vector(body_node)),
            body_shape=shape.shape,
            body_shape_hash=shape.shape_hash,
            body_tree_node_count=shape.node_count,
        ),
        flow=OperationFlow(
            call_fingerprints=tuple(calls),
            parameter_use_vectors=tuple(sorted(parameter_vectors.items())),
            parameter_default_roles=tuple(sorted(defaults.items())),
            local_dataflow_graph=graph,
        ),
    )


def _empty_features() -> OperationFeatures:
    return OperationFeatures()


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
    return [_statement_token(source, stmt, args, locals_) for stmt in _body_statements(body_node)]


def _body_statements(body_node: Node) -> list[Node]:
    if body_node.type == "statement_block":
        return list(body_node.named_children)
    return [body_node]


def _statement_token(  # noqa: PLR0911
    source: bytes,
    stmt: Node,
    args: dict[str, str],
    locals_: set[str],
) -> str:
    if stmt.type == "expression_statement":
        call = _first_call(stmt)
        if call is not None:
            return "CALL:" + _call_fingerprint(source, call, args, locals_).token
    if stmt.type in CALL_TYPES:
        return "CALL:" + _call_fingerprint(source, stmt, args, locals_).token
    if stmt.type == "return_statement":
        return "RETURN:" + ",".join(sorted(_arg_reads(source, stmt, args)))
    if stmt.type in ASSIGN_TYPES:
        return "ASSIGN:" + stmt.type
    if stmt.type in BRANCH_TYPES:
        return "IF" if stmt.type == "if_statement" else stmt.type.upper()
    if stmt.type in LOOP_TYPES:
        return "LOOP"
    if stmt.type in TRY_TYPES:
        return "TRY"
    return stmt.type.upper()


def _first_call(node: Node) -> Node | None:
    return next((child for child in iter_named_nodes(node) if child.type in CALL_TYPES), None)


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


def _graph_features(graph: DataflowGraph) -> set[str]:
    features = {f"node:{node.kind}:{node.label}" for node in graph.nodes}
    features.update(
        f"edge:{edge.kind}:{edge.from_id}:{edge.from_label}->{edge.to_id}:{edge.to_label}"
        for edge in graph.edges
    )
    return features


def _literal_shapes(default_roles: dict[str, str], calls: list[CallFingerprint]) -> set[str]:
    shapes = {value for value in default_roles.values() if value.startswith("CONST_")}
    for call in calls:
        shapes.update(value for value in call.arg_roles if value.startswith("CONST_"))
        shapes.update(
            value for value in call_kwarg_shape_values(call) if value.startswith("CONST_")
        )
    return shapes


def _receiver_shapes(calls: list[CallFingerprint]) -> set[str]:
    shapes: set[str] = set()
    for call in calls:
        receiver = call.receiver_shape
        if receiver is None:
            continue
        access = ".".join(receiver.access_path)
        if shape := f"{receiver.base}.{access}".rstrip("."):
            shapes.add(shape)
    return shapes


def _parameter_vector_features(vector: ParameterUseVector) -> set[str]:
    features: set[str] = set()
    features.update(f"access_paths:{item}" for item in vector.access_paths)
    features.update(f"receiver_of_calls:{item}" for item in vector.receiver_of_calls)
    features.update(f"passed_as_argument_to:{item}" for item in vector.passed_as_argument_to)
    features.add(f"returned:{vector.returned}")
    return features


def _normalization_transform_tokens(calls: list[CallFingerprint]) -> set[str]:
    tokens: set[str] = set()
    for call in calls:
        receiver = call.receiver_shape
        if receiver is None or receiver.base != "ARG0" or receiver.access_path:
            continue
        if not _all_constant_roles(call.arg_roles):
            continue
        if not _all_constant_roles(call_kwarg_shape_values(call)):
            continue
        callee = "_".join(item for item in call.callee_shape.name_tokens if item)
        if callee in {"decode", "encode"} and call.token:
            tokens.add(call.token)
    return tokens


def _all_constant_roles(values: tuple[str, ...]) -> bool:
    return all(value.startswith("CONST_") for value in values)


def _statement_arg_reads(graph: DataflowGraph) -> tuple[tuple[int, tuple[str, ...]], ...]:
    reads: list[tuple[int, tuple[str, ...]]] = []
    for node in graph.nodes:
        if node.kind != "statement" or not node.id.startswith("STMT") or not node.arg_reads:
            continue
        match = _STMT_ID_RE.match(node.id)
        if match is not None:
            reads.append((int(match.group("index")), node.arg_reads))
    return tuple(reads)


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
    statements = _body_statements(node)
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
                from_id=role,
                to_id=stmt_id,
                kind="arg_read",
                from_label=role,
                to_label=label,
            )
            for role in sorted(_arg_reads(source, stmt, args))
        )
        if index:
            previous = f"STMT{index - 1}"
            edges.append(
                DataflowEdge(
                    from_id=previous,
                    to_id=stmt_id,
                    kind="lexical_order",
                    from_label=sequence[index - 1],
                    to_label=label,
                )
            )
        for name in sorted(_local_reads(source, stmt, locals_)):
            if name in local_defs:
                edges.append(
                    DataflowEdge(
                        from_id=local_defs[name],
                        to_id=stmt_id,
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
    return {f"ARG{index}": "DEFAULT" for index, param in enumerate(params) if param.has_default}


def _control_context_vector(node: Node) -> list[str]:
    kinds = []
    for child in iter_named_nodes(node):
        if child.type in LOOP_TYPES:
            kinds.append("LOOP")
        elif child.type in BRANCH_TYPES:
            kinds.append("BRANCH")
        elif child.type in TRY_TYPES:
            kinds.append("TRY")
        elif child.type in CATCH_TYPES:
            kinds.append("CATCH")
        elif child.type == "await_expression":
            kinds.append("AWAIT")
    return sorted(set(kinds))
