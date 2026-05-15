from __future__ import annotations

from dataclasses import replace

from signatures.factories import signature, signature_record

from codeseam.analysis import OrderedTree, signature_core_from_record
from codeseam.output.serializers.signatures import signature_record_payload

EXPECTED_DEBUG_TREE_NODE_COUNT = 2


def test_signature_record_serializes_without_generic_dataclass_walk() -> None:
    record = signature("sig_1", "Python", "src/a.py", "fn", "fn()->T", "h")
    record = replace(
        record,
        function_id="fn_1",
        body_tree_node_count=EXPECTED_DEBUG_TREE_NODE_COUNT,
    )

    payload = signature_record_payload(record)

    assert payload["schema_version"] == "codeseam.signature.v1"
    assert payload["signature_id"] == "sig_1"
    assert payload["function_id"] == "fn_1"
    assert payload["language_family"] == "python"
    assert payload["body_tree"] is None
    assert payload["body_tree_node_count"] == EXPECTED_DEBUG_TREE_NODE_COUNT
    assert payload["graph_features"] == []


def test_signature_record_can_emit_debug_body_tree_on_demand() -> None:
    record = signature_record("sig_1", "Python", "src/a.py", "fn", "fn()->T", "h")
    record.body_tree = OrderedTree("Module", (OrderedTree("Return"),))

    payload = signature_record_payload(
        signature_core_from_record(record),
        body_tree=record.body_tree,
    )

    assert payload["body_tree"] == {
        "label": "Module",
        "children": [{"label": "Return", "children": []}],
    }
