from __future__ import annotations

from codeseam.analysis import (
    ROLE_STATEMENT_SEQUENCE_DELTA,
    OrderedTree,
    SequenceTemplateItem,
    anti_unify_sequences,
    anti_unify_trees,
)


def test_sequence_skeleton_keeps_exact_matches_hole_free() -> None:
    EXPECTED_EXACT_STABLE_STATEMENTS = 2

    skeleton = anti_unify_sequences(
        ["CALL:ARG0.parse", "RETURN:ARG0"],
        ["CALL:ARG0.parse", "RETURN:ARG0"],
        left_id="left_fn",
        right_id="right_fn",
    )

    assert skeleton.template == (
        SequenceTemplateItem("STABLE_STATEMENT", token="CALL:ARG0.parse"),
        SequenceTemplateItem("STABLE_STATEMENT", token="RETURN:ARG0"),
    )
    assert skeleton.hole_count == 0
    assert skeleton.stable_statement_count == EXPECTED_EXACT_STABLE_STATEMENTS
    assert skeleton.stable_node_ratio == 1.0
    assert skeleton.hole_bindings == {"left_fn": {}, "right_fn": {}}


def test_sequence_skeleton_exposes_common_prefix_and_divergent_tail() -> None:
    EXPECTED_DIVERGENT_STABLE_RATIO = 0.2
    EXPECTED_DIVERGENT_MAX_HOLE_SIZE = 4

    skeleton = anti_unify_sequences(
        [
            "CALL:ARG0.parent.mkdir",
            "CALL:ARG0.write_text(ARG1,encoding=CONST_STR)",
        ],
        [
            "CALL:ARG0.parent.mkdir",
            "WITH:NamedTemporaryFile(encoding=CONST_STR,dir=ARG0.parent)",
            "CALL:LOCAL.write(ARG1)",
            "ASSIGN:LOCAL=LOCAL.name",
            "CALL:os.replace(LOCAL,ARG0)",
        ],
        left_id="direct_write",
        right_id="atomic_write",
    )

    assert skeleton.template[0] == SequenceTemplateItem(
        "STABLE_STATEMENT",
        token="CALL:ARG0.parent.mkdir",
    )
    assert skeleton.template[1].kind == "HOLE"
    assert skeleton.template[1].id == "H0"
    assert skeleton.template[1].roles == (
        "call_delta",
        "literal_delta",
        "receiver_delta",
        "branch_delta",
    )
    assert skeleton.hole_bindings["direct_write"]["H0"] == (
        "CALL:ARG0.write_text(ARG1,encoding=CONST_STR)",
    )
    assert skeleton.hole_bindings["atomic_write"]["H0"] == (
        "WITH:NamedTemporaryFile(encoding=CONST_STR,dir=ARG0.parent)",
        "CALL:LOCAL.write(ARG1)",
        "ASSIGN:LOCAL=LOCAL.name",
        "CALL:os.replace(LOCAL,ARG0)",
    )
    assert skeleton.stable_statement_count == 1
    assert skeleton.stable_node_ratio == EXPECTED_DIVERGENT_STABLE_RATIO
    assert skeleton.common_prefix_length == 1
    assert skeleton.hole_count == 1
    assert skeleton.max_hole_size == EXPECTED_DIVERGENT_MAX_HOLE_SIZE
    assert skeleton.hole_size_variance == "high"
    assert skeleton.shared_param_flow_through_holes is True


def test_sequence_skeleton_uses_lcs_for_non_contiguous_common_core() -> None:
    EXPECTED_LCS_STABLE_STATEMENTS = 2
    EXPECTED_LCS_HOLE_COUNT = 2

    skeleton = anti_unify_sequences(
        ["SETUP", "CALL:validate(ARG0)", "RETURN:ARG0"],
        ["CALL:log(ARG0)", "CALL:validate(ARG0)", "CALL:save(ARG0)", "RETURN:ARG0"],
    )

    assert skeleton.stable_statement_count == EXPECTED_LCS_STABLE_STATEMENTS
    assert [item.kind for item in skeleton.template] == [
        "HOLE",
        "STABLE_STATEMENT",
        "HOLE",
        "STABLE_STATEMENT",
    ]
    assert skeleton.hole_bindings["left"]["H0"] == ("SETUP",)
    assert skeleton.hole_bindings["right"]["H0"] == ("CALL:log(ARG0)",)
    assert skeleton.hole_bindings["left"]["H1"] == ()
    assert skeleton.hole_bindings["right"]["H1"] == ("CALL:save(ARG0)",)
    assert skeleton.hole_count == EXPECTED_LCS_HOLE_COUNT
    assert skeleton.hole_size_variance == "low"


def test_sequence_skeleton_uses_one_whole_region_hole_when_nothing_matches() -> None:
    skeleton = anti_unify_sequences(["RETURN:ARG0"], ["RAISE:ValueError"])

    assert skeleton.template == (
        SequenceTemplateItem(
            "HOLE",
            id="H0",
            role=ROLE_STATEMENT_SEQUENCE_DELTA,
            roles=("error_delta", "return_delta"),
        ),
    )
    assert skeleton.stable_statement_count == 0
    assert skeleton.hole_count == 1
    assert skeleton.max_hole_size == 1


def test_tree_skeleton_exposes_inserted_child_holes() -> None:
    EXPECTED_STABLE_NODES = 3
    EXPECTED_MAX_HOLE_SIZE = 2
    EXPECTED_STABLE_RATIO = 0.6

    left = OrderedTree(
        "Module",
        (
            OrderedTree("Assign"),
            OrderedTree("Return"),
        ),
    )
    right = OrderedTree(
        "Module",
        (
            OrderedTree("Assign"),
            OrderedTree("If", (OrderedTree("Call"),)),
            OrderedTree("Return"),
        ),
    )

    skeleton = anti_unify_trees(left, right, left_id="simple", right_id="guarded")

    assert skeleton.template == OrderedTree(
        "Module",
        (
            OrderedTree("Assign"),
            OrderedTree("HOLE:H0"),
            OrderedTree("Return"),
        ),
    )
    assert skeleton.hole_bindings["simple"]["H0"] == ()
    assert skeleton.hole_bindings["guarded"]["H0"] == (OrderedTree("If", (OrderedTree("Call"),)),)
    assert skeleton.stable_node_count == EXPECTED_STABLE_NODES
    assert skeleton.stable_node_ratio == EXPECTED_STABLE_RATIO
    assert skeleton.hole_count == 1
    assert skeleton.max_hole_size == EXPECTED_MAX_HOLE_SIZE


def test_tree_skeleton_uses_root_hole_for_different_nodes() -> None:
    skeleton = anti_unify_trees(OrderedTree("Return"), OrderedTree("Raise"))

    assert skeleton.template == OrderedTree("HOLE:H0")
    assert skeleton.hole_count == 1
    assert skeleton.stable_node_count == 0
    assert skeleton.stable_node_ratio == 0.0
    assert skeleton.hole_bindings["left"]["H0"] == (OrderedTree("Return"),)
    assert skeleton.hole_bindings["right"]["H0"] == (OrderedTree("Raise"),)
