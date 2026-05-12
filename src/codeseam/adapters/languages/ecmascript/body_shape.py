from __future__ import annotations

from dataclasses import dataclass

from tree_sitter import Node

from codeseam.adapters.languages.ecmascript.runtime import iter_named_nodes, node_text
from codeseam.analysis import ParamIR
from codeseam.platform import normalize_identifier, sha256_text

BODY_SHAPE_SCHEMA = "ecmascript_body_shape_v1"
IGNORED_NODE_TYPES = frozenset({"comment"})
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
    return BodyShape(
        shape=shape,
        shape_hash=sha256_text(f"{BODY_SHAPE_SCHEMA}\n{shape}"),
        node_count=node_count,
    )


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

    def write(self, node: Node) -> tuple[str, int]:
        tokens: list[str] = []
        count = self._append(node, tokens)
        return " ".join(tokens), count

    def _append(self, node: Node, tokens: list[str]) -> int:
        if node.type in IGNORED_NODE_TYPES:
            return 0
        tokens.append(self._token(node))
        count = 1
        children = [child for child in node.named_children if child.type not in IGNORED_NODE_TYPES]
        if children:
            tokens.append("(")
            for child in children:
                count += self._append(child, tokens)
            tokens.append(")")
        return count

    def _token(self, node: Node) -> str:
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
        return token

    def _identifier_token(self, node: Node) -> str:
        text = node_text(self.source, node) or ""
        if role := self.param_roles.get(text):
            return role
        if role := self.local_roles.get(text):
            return role
        return f"ID:{normalize_identifier(text)}"

    def _literal_token(self, kind: str, node: Node) -> str:
        if not self.preserve_literals:
            return f"LIT:{kind}"
        return f"LIT:{kind}:{node_text(self.source, node) or ''}"


def _normalized_text(source: bytes, node: Node) -> str:
    return normalize_identifier(node_text(source, node) or node.type) or node.type


__all__ = ["BodyShape", "normalized_body_shape", "parameter_roles"]
