"""Statement keys align at Type-2; body trees keep exact values and operators."""

from __future__ import annotations

import ast
from collections.abc import Callable
from pathlib import Path

import pytest
import tree_sitter_typescript as tstypescript
from helpers import extract_source
from tree_sitter import Language

from codeseam.adapters.languages.ecmascript.body_shape import body_tree as ts_body_tree
from codeseam.adapters.languages.ecmascript.runtime import TreeSitterRuntime, iter_named_nodes
from codeseam.adapters.languages.python.signature_features import body_tree as py_body_tree
from codeseam.analysis import OrderedTree, ParamIR
from codeseam.analysis.relations.tree_distance import body_tree_edit_distance
from codeseam.analysis.relations.unification import operator_changed
from codeseam.analysis.signatures import SignatureRecord

TYPESCRIPT = TreeSitterRuntime.from_language(
    "typescript", Language(tstypescript.language_typescript())
)
STATEMENT_COUNT_WITH_COMMENT = 2


def _signature(tmp_path: Path, language: str, source: str, name: str) -> SignatureRecord:
    (signature,) = extract_source(tmp_path / name, language, source).signatures
    return signature


@pytest.mark.parametrize(
    ("language", "left", "right", "same"),
    [
        (
            "Python",
            "def f(path):\n    raw = path.read()\n    return User.load(raw['users'])\n",
            "def g(src):\n    text = src.read()\n    return Order.load(text['orders'])\n",
            True,
        ),
        ("Python", "def f(a, b):\n    return a + b\n", "def f(a, b):\n    return a - b\n", False),
        (
            "Python",
            "def f(x):\n    return read_json(x)\n",
            "def f(x):\n    return delete_all(x)\n",
            False,
        ),
        (
            "TypeScript",
            "function f(p) { const r = p.read(); return User.load(r['users']); }",
            "function g(s) { const t = s.read(); return Order.load(t['orders']); }",
            True,
        ),
        (
            "TypeScript",
            "function f(a, b) { return a + b; }",
            "function f(a, b) { return a - b; }",
            False,
        ),
    ],
    ids=["py-data-only", "py-operator", "py-callee", "ts-data-only", "ts-operator"],
)
def test_statement_keys_align_data_changes_but_not_operations(
    tmp_path: Path, language: str, left: str, right: str, same: bool
) -> None:
    left_keys = _signature(tmp_path, language, left, "left").statement_keys
    right_keys = _signature(tmp_path, language, right, "right").statement_keys

    assert left_keys and (left_keys == right_keys) is same


def test_unrelated_assign_assign_return_bodies_share_no_statement_keys(tmp_path: Path) -> None:
    left = _signature(
        tmp_path,
        "Python",
        "def f(uid):\n    user = repo.get(uid)\n"
        "    name = user.first + ' ' + user.last\n    return name.title()\n",
        "left",
    )
    right = _signature(
        tmp_path,
        "Python",
        "def g(blob):\n    data = blob.encode('utf-8')\n"
        "    digest = hashlib.sha256(data)\n    return digest.hexdigest()\n",
        "right",
    )

    assert left.statement_sequence == right.statement_sequence
    assert not set(left.statement_keys) & set(right.statement_keys)


def test_typescript_comments_are_not_statements(tmp_path: Path) -> None:
    signature = _signature(
        tmp_path,
        "TypeScript",
        "function f(a) {\n  // explain\n  const b = a + 1;\n  return b;\n}",
        "commented",
    )

    assert len(signature.statement_keys) == len(signature.statement_sequence)
    assert len(signature.statement_sequence) == STATEMENT_COUNT_WITH_COMMENT


def _python_tree(source: str) -> OrderedTree:
    (node,) = ast.parse(source).body
    assert isinstance(node, ast.FunctionDef)
    tree = py_body_tree(node)
    assert tree is not None
    return tree


def _typescript_tree(source: str) -> OrderedTree:
    encoded = source.encode()
    node = next(
        item
        for item in iter_named_nodes(TYPESCRIPT.parse(encoded).root_node)
        if item.type == "function_declaration"
    )
    parameters = node.child_by_field_name("parameters")
    assert parameters is not None
    params = tuple(
        ParamIR(annotation=None, name=child.text.decode() if child.text else None)
        for child in iter_named_nodes(parameters)
        if child.type == "identifier"
    )
    tree = ts_body_tree(encoded, node.child_by_field_name("body"), params)
    assert tree is not None
    return tree


@pytest.mark.parametrize(
    ("tree", "left", "right", "distance", "operator"),
    [
        (
            _python_tree,
            "def f(a, b):\n    return a + b\n",
            "def f(a, b):\n    return a - b\n",
            1,
            True,
        ),
        (
            _python_tree,
            "def f(u):\n    if not u.active:\n        return 0\n    return 1\n",
            "def f(u):\n    if u.active:\n        return 0\n    return 1\n",
            4,  # top-down distance: unwrapping `not` relabels and deletes children
            True,
        ),
        (
            _python_tree,
            "def f(v):\n    use(v)\n",
            "def f(v):\n    if v == '':\n        return\n    use(v)\n",
            6,
            False,
        ),
        (
            _python_tree,
            "def f(u, b):\n    if not u.ok:\n        return False\n    if b.total <= 0:\n"
            "        return False\n    return True\n",
            "def f(u, b):\n    if b.total <= 0:\n        return False\n    if not u.ok:\n"
            "        return False\n    return True\n",
            0,
            False,
        ),
        (
            _typescript_tree,
            "function f(a, b) { return a + b; }",
            "function f(a, b) { return a - b; }",
            1,
            True,
        ),
        (_typescript_tree, "function f(a) { return !a; }", "function f(a) { return a; }", 3, True),
    ],
    ids=[
        "py-substitution",
        "py-negation",
        "py-insert",
        "py-reorder",
        "ts-substitution",
        "ts-negation",
    ],
)
def test_body_trees_measure_edits_and_operator_changes(
    tree: Callable[[str], OrderedTree], left: str, right: str, distance: int, operator: bool
) -> None:
    left_tree, right_tree = tree(left), tree(right)

    assert body_tree_edit_distance(left_tree, right_tree) == distance
    assert operator_changed(left_tree, right_tree) is operator


def test_python_body_tree_resolves_names_like_the_body_hash() -> None:
    tree = _python_tree("def f(account):\n    total = account.balance + FEE\n    return total\n")

    assign, ret = tree.children
    assert assign.children[0].label == "Name:LOCAL0"
    assert [child.label for child in assign.children[1].children] == [
        "Attribute:balance",
        "op:Add",
        "Name:FREE:FEE",
    ]
    assert ret.children[0].label == "Name:LOCAL0"
