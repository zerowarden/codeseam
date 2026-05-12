from __future__ import annotations

from collections import Counter
from pathlib import Path

from codeseam.analysis import (
    OrderedTree,
    ordered_tree_edit_distance,
    ordered_tree_size,
)
from codeseam.platform import (
    basename,
    cached_identifier_tokens,
    counter_jaccard,
    identifier_tokens,
    is_binary,
    is_public_identifier,
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


def test_ordered_tree_edit_distance_scores_relabels_and_inserts() -> None:
    left = OrderedTree("Module", (OrderedTree("Return"),))
    relabeled = OrderedTree("Module", (OrderedTree("Raise"),))
    inserted = OrderedTree("Module", (OrderedTree("Return"), OrderedTree("Name")))

    assert ordered_tree_size(inserted) == TREE_SIZE
    assert ordered_tree_edit_distance(left, left) == 0
    assert ordered_tree_edit_distance(left, relabeled) == 1
    assert ordered_tree_edit_distance(left, inserted) == 1


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
