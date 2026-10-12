from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from codeseam.analysis import (
    OrderedTree,
    ordered_tree_edit_distance,
    ordered_tree_size,
)
from codeseam.analysis.relations.tree_distance import tree_shape
from codeseam.platform import (
    basename,
    cached_identifier_tokens,
    counter_jaccard,
    identifier_tokens,
    is_binary,
    is_public_identifier,
    jaccard,
    json_digest,
    json_float,
    json_text_keys,
    levenshtein_distance,
    line_count,
    load_jsonl_objects,
    matches_any,
    mean_jaccard_by_key,
    normalize_identifier,
    parent_path,
    path_parts,
    plural_noun,
    plural_suffix,
    sha256_text,
    similarity_ratio,
    single_line,
    string_tuple,
    with_overrides,
    write_jsonable_atomic,
    write_jsonl_jsonable_atomic,
)

TWO_LINES = 2
LOW_SIMILARITY = 0.5
EXPECTED_COUNTER_RATIO = 0.25
TREE_SIZE = 3
EXPECTED_PREAMBLE_RATIO = 0.75
EXPECTED_MULTILINE_IMPORT_LINES = 4
EXPECTED_JSONL_OBJECT_COUNT = 2
EXPECTED_JSON_FLOAT = 1.5
DEFAULT_JSON_FLOAT = -1.0


def test_matches_any_supports_default_basename_and_directory_patterns() -> None:
    assert matches_any("src/app.py", ["**/*"])
    assert matches_any("tests/test_app.py", ["**/test_*.py"])
    assert matches_any("node_modules/pkg/index.js", ["node_modules/**"])
    assert not matches_any("src/app.py", ["dist/**"])


def test_path_helpers_share_posix_part_splitting() -> None:
    parts = path_parts("src/pkg/module.py")

    assert parts == ["src", "pkg", "module.py"]
    assert basename("src/pkg/module.py") == parts[-1]
    assert parent_path("src/pkg/module.py") == "/".join(parts[:-1])
    assert basename("module.py") == "module.py"
    assert parent_path("module.py") == ""


def test_file_helpers_are_conservative(tmp_path: Path) -> None:
    text = tmp_path / "text.txt"
    binary = tmp_path / "binary.bin"
    text.write_text("a\nb", encoding="utf-8")
    binary.write_bytes(b"a\0b")

    assert line_count(text.read_bytes()) == TWO_LINES
    assert not is_binary(text)
    assert is_binary(binary)
    assert sha256_text("x").startswith("sha256:")


def test_string_helpers_normalize_identifiers_and_score_similarity() -> None:
    assert normalize_identifier("_parseJSONValue") == "parse json value"
    assert identifier_tokens("_parseJSONValue") == ["parse", "json", "value"]
    assert cached_identifier_tokens("_parseJSONValue") == ("parse", "json", "value")
    assert cached_identifier_tokens("_parseJSONValue") is cached_identifier_tokens(
        "_parseJSONValue"
    )
    assert is_public_identifier("parseJSONValue")
    assert not is_public_identifier("_parseJSONValue")
    assert levenshtein_distance("text", "test") == 1
    assert similarity_ratio("text", "text") == 1.0
    assert similarity_ratio("text", "value") < LOW_SIMILARITY
    assert plural_suffix(1) == ""
    assert plural_suffix(2) == "s"
    assert plural_noun(1, "Reason") == "Reason"
    assert plural_noun(2, "Reason") == "Reasons"
    assert plural_noun(2, "analysis", "analyses") == "analyses"
    assert string_tuple(["a", 2, "b"]) == ("a", "b")
    assert string_tuple(["a", 2, "b"], coerce=True) == ("a", "2", "b")
    assert single_line("  src/app.py:\n  10 ") == "src/app.py: 10"


def test_similarity_helpers_score_sets_and_counters() -> None:
    assert (
        counter_jaccard(Counter({"a": 2, "b": 1}), Counter({"a": 1, "c": 1}))
        == EXPECTED_COUNTER_RATIO
    )
    assert (
        mean_jaccard_by_key(
            {"ARG0": {"read", "write"}, "ARG1": {"pass"}},
            {"ARG0": {"read"}, "ARG1": {"pass"}},
        )
        == EXPECTED_PREAMBLE_RATIO
    )


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (lambda: jaccard(set(), set()), 0.0),
        (lambda: counter_jaccard(Counter(), Counter()), 0.0),
        (lambda: mean_jaccard_by_key({"ARG0": set()}, {"ARG0": set()}), 0.0),
        (lambda: mean_jaccard_by_key({"ARG0": {"read"}, "ARG1": set()}, {"ARG0": {"read"}}), 1.0),
    ],
    ids=["empty-sets", "empty-counters", "unused-key", "unused-key-is-skipped"],
)
def test_shared_absence_is_not_similarity(score: Callable[[], float], expected: float) -> None:
    assert score() == expected


def _t(label: str, *children: OrderedTree) -> OrderedTree:
    return OrderedTree(label, children)


@pytest.mark.parametrize(
    ("left", "right", "distance"),
    [
        (_t("m", _t("ret")), _t("m", _t("ret")), 0),
        (_t("m", _t("ret")), _t("m", _t("raise")), 1),
        (_t("m", _t("ret")), _t("m", _t("ret"), _t("name")), 1),
        (_t("r", _t("a"), _t("b")), _t("r", _t("b")), 1),
        (_t("r"), _t("r", _t("a", _t("b"), _t("c"))), 3),
        (_t("f", _t("a"), _t("b", _t("c"))), _t("f", _t("a"), _t("x", _t("c")), _t("d")), 2),
    ],
    ids=["same", "relabel", "insert", "delete-first", "insert-subtree", "relabel-and-insert"],
)
def test_ordered_tree_edit_distance(left: OrderedTree, right: OrderedTree, distance: int) -> None:
    assert ordered_tree_edit_distance(left, right) == distance
    assert ordered_tree_edit_distance(right, left) == distance


def test_ordered_tree_size_and_shape() -> None:
    tree = _t("Module", _t("Return"), _t("Name"))
    relabeled = _t("Body", _t("Raise"), _t("Attr"))

    assert ordered_tree_size(tree) == TREE_SIZE
    assert tree_shape(tree) == tree_shape(relabeled) != tree_shape(_t("Module", _t("Return")))


def test_json_helpers_keep_common_json_actions_in_one_place(tmp_path: Path) -> None:
    object_path = tmp_path / "object.json"
    jsonl_path = tmp_path / "records.jsonl"

    write_jsonable_atomic(object_path, {"b": 2, "a": 1}, pretty=True)
    write_jsonl_jsonable_atomic(jsonl_path, [{"id": "a"}, {"id": "b"}, "skip"])

    assert object_path.exists()
    assert json_float("1.5") == EXPECTED_JSON_FLOAT
    assert json_float(None, default=DEFAULT_JSON_FLOAT) == DEFAULT_JSON_FLOAT
    assert json_text_keys({"items": {"b": 2, "a": 1}}, "items") == ["a", "b"]
    assert json_digest({"b": 2, "a": 1}) == json_digest({"a": 1, "b": 2})
    assert len(load_jsonl_objects(jsonl_path)) == EXPECTED_JSONL_OBJECT_COUNT


@dataclass(frozen=True)
class _Inner:
    count: int = 1
    ratio: float = 0.5
    enabled: bool = False


@dataclass(frozen=True)
class _Outer:
    label: str = "x"
    inner: _Inner = field(default_factory=_Inner)


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"inner": {"count": 3}}, _Outer(inner=_Inner(count=3))),
        ({"inner": {"ratio": 1}}, _Outer(inner=_Inner(ratio=1.0))),
        ({"label": "y", "inner": {"enabled": True}}, _Outer("y", _Inner(enabled=True))),
    ],
    ids=["nested-int", "int-for-float", "str-and-bool"],
)
def test_with_overrides_applies_typed_values(
    overrides: dict[str, object], expected: _Outer
) -> None:
    assert with_overrides(_Outer(), overrides) == expected


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"missing": 1}, "unknown setting 'missing'"),
        ({"inner": {"count": 1.5}}, "'inner.count' must be int"),
        ({"inner": {"count": True}}, "'inner.count' must be int"),
        ({"inner": {"enabled": 1}}, "'inner.enabled' must be bool"),
        ({"inner": 2}, "'inner' is a table"),
    ],
    ids=["unknown", "float-for-int", "bool-for-int", "int-for-bool", "scalar-for-table"],
)
def test_with_overrides_rejects_invalid_values(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        with_overrides(_Outer(), overrides)
