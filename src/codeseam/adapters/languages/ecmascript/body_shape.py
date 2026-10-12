from __future__ import annotations

from dataclasses import dataclass
from hashlib import blake2b

from tree_sitter import Node

from codeseam.adapters.languages.ecmascript.runtime import iter_named_nodes, node_text
from codeseam.analysis import ParamIR
from codeseam.analysis.signatures import MAX_TREE_DEPTH, OrderedTree
from codeseam.platform import normalize_identifier, sha256_text

BODY_SHAPE_SCHEMA = "ecmascript_body_shape_v2"
STATEMENT_KEY_BYTES = 8
IGNORED_NODE_TYPES = frozenset({"comment"})
# Anonymous tokens that change behaviour: `a + b` vs `a - b`, `for in` vs `for of`,
# `let` vs `const`. Named-child traversal alone would erase them.
SYNTAX_DETAIL_FIELDS = ("operator", "kind")
LOCAL_BINDING_TYPES = frozenset(
    {
        "variable_declarator",
        "function_declaration",
        "class_declaration",
        "catch_clause",
    }
)
STRING_TYPES = frozenset({"string", "template_string", "regex"})
NUMBER_TYPES = frozenset({"number"})
BOOLEAN_TYPES = frozenset({"true", "false"})
NONE_TYPES = frozenset({"null", "undefined"})
PROPERTY_TYPES = frozenset(
    {
        "property_identifier",
        "private_property_identifier",
    }
)
TYPE_NAME_TYPES = frozenset(
    {
        "type_identifier",
        "predefined_type",
        "generic_type",
    }
)


@dataclass(frozen=True, slots=True)
class BodyShape:
    shape: str = ""
    shape_hash: str = ""
    node_count: int = 0
    statement_keys: tuple[str, ...] = ()
    statement_spans: tuple[tuple[int, int], ...] = ()


def normalized_body_shape(
    source: bytes,
    body_node: Node | None,
    params: tuple[ParamIR, ...],
    *,
    preserve_literals: bool = False,
) -> BodyShape:
    """Return a compact implementation identity for JS/TS function bodies.

    Tree-sitter gives us portable syntax facts without requiring a TypeScript
    compiler. This shape is intentionally syntactic: it normalizes parameters
    and local bindings so renamed clones can match, while preserving external
    callee/property names so different operations do not collapse together.
    Declaration signatures and empty bodies return no hash because they are API
    surface facts, not implementation evidence.
    """

    if body_node is None:
        return BodyShape()
    param_roles = parameter_roles(params)
    local_roles = _local_roles(source, body_node, param_roles)
    writer = _BodyShapeWriter(source, param_roles, local_roles, preserve_literals)
    shape, node_count = writer.write(body_node)
    if not node_count:
        return BodyShape()
    key_writer = _BodyShapeWriter(source, param_roles, local_roles, abstract_free=True)
    return BodyShape(
        shape=shape,
        shape_hash=sha256_text(f"{BODY_SHAPE_SCHEMA}\n{shape}"),
        node_count=node_count,
        statement_keys=tuple(
            blake2b(
                key_writer.write(statement)[0].encode("utf-8", "surrogatepass"),
                digest_size=STATEMENT_KEY_BYTES,
            ).hexdigest()
            for statement in body_statements(body_node)
        ),
        statement_spans=tuple(
            (statement.start_point[0] + 1, statement.end_point[0] + 1)
            for statement in body_statements(body_node)
        ),
    )


def body_tree(
    source: bytes, body_node: Node | None, params: tuple[ParamIR, ...]
) -> OrderedTree | None:
    """Normalized body tree for tree-edit distance, labelled like the body shape.

    Operators become `op:` leaves instead of label suffixes, so an operator change
    is one relabel and stays visible to operator-delta checks.
    """

    if body_node is None:
        return None
    param_roles = parameter_roles(params)
    writer = _BodyShapeWriter(source, param_roles, _local_roles(source, body_node, param_roles))
    statements = [writer.tree(stmt) for stmt in body_statements(body_node)]
    if any(statement is None for statement in statements):
        return None
    return OrderedTree("body", tuple(statement for statement in statements if statement))


def body_statements(body_node: Node) -> list[Node]:
    """Top-level statements; an arrow function's expression body is one statement."""

    if body_node.type == "statement_block":
        return [child for child in body_node.named_children if child.type not in IGNORED_NODE_TYPES]
    return [body_node]


def parameter_roles(params: tuple[ParamIR, ...]) -> dict[str, str]:
    return {param.name: f"ARG{index}" for index, param in enumerate(params) if param.name}


def _local_roles(
    source: bytes,
    body_node: Node,
    param_roles: dict[str, str],
) -> dict[str, str]:
    roles: dict[str, str] = {}
    for node in iter_named_nodes(body_node):
        if node.type in LOCAL_BINDING_TYPES:
            for name in _binding_names(source, node):
                if name not in param_roles and name not in roles:
                    roles[name] = f"LOCAL{len(roles)}"
    return roles


def _binding_names(source: bytes, node: Node) -> tuple[str, ...]:
    names: list[str] = []
    for field in ("name", "parameter"):
        names.extend(_target_names(source, node.child_by_field_name(field)))
    return tuple(dict.fromkeys(names))


def _target_names(source: bytes, node: Node | None) -> tuple[str, ...]:
    if node is None:
        return ()
    if node.type == "identifier":
        text = node_text(source, node)
        return (text,) if text else ()
    return tuple(
        dict.fromkeys(
            text
            for child in iter_named_nodes(node)
            if child.type == "identifier" and (text := node_text(source, child))
        )
    )


@dataclass(frozen=True, slots=True)
class _BodyShapeWriter:
    source: bytes
    param_roles: dict[str, str]
    local_roles: dict[str, str]
    preserve_literals: bool = False
    # Statement keys align at Type-2: free names outside call position collapse.
    abstract_free: bool = False

    def write(self, node: Node) -> tuple[str, int]:
        tokens: list[str] = []
        count = 0
        stack: list[Node | str] = [node]  # iterative: nesting depth is unbounded
        while stack:
            item = stack.pop()
            if isinstance(item, str):
                tokens.append(item)
                continue
            if item.type in IGNORED_NODE_TYPES:
                continue
            tokens.append(self._token(item))
            count += 1
            if children := _children(item):
                tokens.append("(")
                stack.append(")")
                stack.extend(reversed(children))
        return " ".join(tokens), count

    def tree(self, node: Node) -> OrderedTree | None:
        """Iterative post-order build; None past `MAX_TREE_DEPTH`."""

        built: dict[int, OrderedTree] = {}
        stack: list[tuple[Node, int, bool]] = [(node, 0, False)]
        while stack:
            current, depth, expanded = stack.pop()
            if depth > MAX_TREE_DEPTH:
                return None
            children = _children(current)
            if not expanded:
                stack.append((current, depth, True))
                stack.extend((child, depth + 1, False) for child in reversed(children))
                continue
            items = [built.pop(child.id) for child in children]
            if (operator := current.child_by_field_name("operator")) is not None:
                items.insert(0, OrderedTree(f"op:{operator.type}"))
            built[current.id] = OrderedTree(
                self._token(current, detail_fields=("kind",)), tuple(items)
            )
        return built[node.id]

    def _token(self, node: Node, detail_fields: tuple[str, ...] = SYNTAX_DETAIL_FIELDS) -> str:
        node_type = node.type
        if node_type == "identifier":
            return self._identifier_token(node)
        token = node_type
        if node_type in PROPERTY_TYPES:
            token = f"PROP:{_normalized_text(self.source, node)}"
        elif node_type in TYPE_NAME_TYPES:
            token = "TYPE"
        elif node_type in STRING_TYPES:
            token = self._literal_token("STR", node)
        elif node_type in NUMBER_TYPES:
            token = self._literal_token("NUM", node)
        elif node_type in BOOLEAN_TYPES | NONE_TYPES:
            token = self._literal_token(node_type.upper(), node)
        else:
            token += _syntax_detail(node, detail_fields)
        return token

    def _identifier_token(self, node: Node) -> str:
        text = node_text(self.source, node) or ""
        if role := self.param_roles.get(text):
            return role
        if role := self.local_roles.get(text):
            return role
        if self.abstract_free and not _is_callee(node):
            return "ID"
        return f"ID:{normalize_identifier(text)}"

    def _literal_token(self, kind: str, node: Node) -> str:
        if not self.preserve_literals:
            return f"LIT:{kind}"
        return f"LIT:{kind}:{node_text(self.source, node) or ''}"


def _children(node: Node) -> list[Node]:
    return [child for child in node.named_children if child.type not in IGNORED_NODE_TYPES]


def _is_callee(node: Node) -> bool:
    parent = node.parent
    if parent is None or parent.type not in {"call_expression", "new_expression"}:
        return False
    callee = parent.child_by_field_name("function") or parent.child_by_field_name("constructor")
    return callee is not None and callee.id == node.id


def _syntax_detail(node: Node, fields: tuple[str, ...]) -> str:
    details = [
        child.type for field in fields if (child := node.child_by_field_name(field)) is not None
    ]
    return f"[{' '.join(details)}]" if details else ""


def _normalized_text(source: bytes, node: Node) -> str:
    return normalize_identifier(node_text(source, node) or node.type) or node.type


__all__ = ["BodyShape", "body_statements", "body_tree", "normalized_body_shape", "parameter_roles"]
