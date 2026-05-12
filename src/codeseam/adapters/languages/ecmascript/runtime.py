from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from tree_sitter import Language, Node, Parser, Tree


@dataclass(frozen=True)
class TreeSitterRuntime:
    language_name: str
    language: Language
    parser: Parser

    @classmethod
    def from_language(cls, language_name: str, language: Language) -> TreeSitterRuntime:
        return cls(language_name=language_name, language=language, parser=Parser(language))

    def parse(self, source: bytes) -> Tree:
        tree = self.parser.parse(source)
        if tree is None:
            raise RuntimeError(f"Tree-sitter parser failed for {self.language_name}")
        return tree


def iter_named_nodes(node: Node) -> Iterable[Node]:
    yield node
    for child in node.named_children:
        yield from iter_named_nodes(child)


def node_text(source: bytes, node: Node | None) -> str | None:
    if node is None:
        return None
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def line_no(node: Node) -> int:
    return node.start_point[0] + 1


__all__ = ["TreeSitterRuntime", "iter_named_nodes", "line_no", "node_text"]
