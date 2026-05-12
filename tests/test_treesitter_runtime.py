from __future__ import annotations

from collections.abc import Callable

import pytest
import tree_sitter_javascript as tsjavascript
import tree_sitter_typescript as tstypescript
from tree_sitter import Language, Node

from codeseam.adapters.languages.ecmascript.runtime import (
    TreeSitterRuntime,
    iter_named_nodes,
)


@pytest.mark.parametrize(
    ("language", "grammar", "source"),
    [
        (
            "javascript",
            tsjavascript.language,
            b"export function load(path) { return path }\n",
        ),
        (
            "typescript",
            tstypescript.language_typescript,
            b"export function load(path: string): Config { return parse(path) }\n",
        ),
    ],
)
def test_treesitter_smoke_parse(
    language: str,
    grammar: Callable[[], object],
    source: bytes,
) -> None:
    runtime = TreeSitterRuntime.from_language(
        language,
        Language(grammar()),
    )

    tree = runtime.parse(source)

    assert tree.root_node.type == "program"
    assert "function_declaration" in _node_types(tree.root_node)


def _node_types(node: Node) -> set[str]:
    return {item.type for item in iter_named_nodes(node)}
