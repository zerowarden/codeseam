from __future__ import annotations

from codeseam.analysis.relations.models import MemberFeatures, SequenceComparison, TreeComparison
from codeseam.analysis.relations.policy import (
    TREE_EDIT_POLICY,
)
from codeseam.analysis.relations.tree_distance import body_tree_edit_distance
from codeseam.analysis.signatures import (
    DataflowGraph,
    OrderedTree,
    ordered_tree_size,
)
from codeseam.platform import (
    common_prefix_length,
    common_suffix_length,
    counter_jaccard,
    jaccard,
    lcs_length,
    mean_jaccard_by_key,
    similarity_ratio,
)

TREE_EDIT_PRODUCT_LIMIT_SOURCE = "tree_edit_skipped_edit_product_limit"
ORDERED_TREE_EDIT_SOURCE = "ordered_tree_edit_distance"
# Only these sources measured the trees; every other source is a proxy and must
# not support exact-structure claims such as `same_tree`.
EXACT_TREE_SOURCES = frozenset({"body_hash", ORDERED_TREE_EDIT_SOURCE})
BODY_SHAPE_TEXT_PRODUCT_LIMIT_SOURCE = "body_shape_text_similarity_skipped_edit_product_limit"
BODY_SHAPE_LAZY_PROXY_SOURCE = "body_shape_lazy_proxy"


def has_body_trees(left: MemberFeatures, right: MemberFeatures) -> bool:
    return left.body_tree is not None and right.body_tree is not None


def tree_edit_product(left: MemberFeatures, right: MemberFeatures) -> int:
    """Return the dynamic-programming work proxy for exact tree edit distance."""
    return _tree_size_for_edit(left) * _tree_size_for_edit(right)


def tree_edit_product_exceeds_limit(left: MemberFeatures, right: MemberFeatures) -> bool:
    return tree_edit_product(left, right) > TREE_EDIT_POLICY.edit_product_limit


def tree_comparison_features(left: MemberFeatures, right: MemberFeatures) -> TreeComparison:
    node_count = max(left.tree_node_count, right.tree_node_count)
    if left.body_hash and left.body_hash == right.body_hash:
        return TreeComparison(1.0, 0.0, 0, node_count, "body_hash")
    if left.body_tree and right.body_tree:
        node_count = max(left.body_tree_size, right.body_tree_size)
        if tree_edit_product_exceeds_limit(left, right):
            return tree_proxy_comparison_features(
                left,
                right,
                proxy_similarity=_tree_edit_proxy_similarity(left, right),
                source=TREE_EDIT_PRODUCT_LIMIT_SOURCE,
            )
        edit_distance = body_tree_edit_distance(left.body_tree, right.body_tree)
        similarity = _similarity_from_distance(edit_distance, node_count)
        return TreeComparison(
            similarity,
            round(1 - similarity, 4),
            edit_distance,
            node_count,
            ORDERED_TREE_EDIT_SOURCE,
        )
    if not left.body_shape or not right.body_shape:
        return tree_proxy_comparison_features(
            left,
            right,
            proxy_similarity=_tree_edit_proxy_similarity(left, right),
            source=BODY_SHAPE_LAZY_PROXY_SOURCE,
        )
    if body_shape_text_product_exceeds_limit(left, right):
        return tree_proxy_comparison_features(
            left,
            right,
            proxy_similarity=_tree_edit_proxy_similarity(left, right),
            source=BODY_SHAPE_TEXT_PRODUCT_LIMIT_SOURCE,
        )
    similarity = similarity_ratio(left.body_shape, right.body_shape)
    return TreeComparison(
        similarity,
        round(1 - similarity, 4),
        None,
        0,
        "body_shape_text_similarity",
    )


def tree_proxy_comparison_features(
    left: MemberFeatures,
    right: MemberFeatures,
    *,
    proxy_similarity: float,
    source: str,
) -> TreeComparison:
    node_count = max(left.tree_node_count, right.tree_node_count)
    similarity = round(max(0.0, min(1.0, proxy_similarity)), 4)
    return TreeComparison(
        similarity,
        round(1 - similarity, 4),
        None,
        node_count,
        source,
    )


def body_shape_text_product(left: MemberFeatures, right: MemberFeatures) -> int:
    """Return the dynamic-programming work proxy for body-shape text similarity."""
    return len(left.body_shape) * len(right.body_shape)


def body_shape_text_product_exceeds_limit(
    left: MemberFeatures,
    right: MemberFeatures,
) -> bool:
    return body_shape_text_product(left, right) > TREE_EDIT_POLICY.edit_product_limit


def sequence_alignment_features(left: MemberFeatures, right: MemberFeatures) -> SequenceComparison:
    left_seq = list(left.aligned_statements)
    right_seq = list(right.aligned_statements)
    lcs = lcs_length(left_seq, right_seq)
    prefix = common_prefix_length(left_seq, right_seq)
    suffix = common_suffix_length(left_seq, right_seq)
    max_len = max(len(left_seq), len(right_seq), 1)
    return SequenceComparison(
        lcs_length=lcs,
        common_prefix_length=prefix,
        common_suffix_length=suffix,
        inserted_block_count=1 if lcs and len(left_seq) != len(right_seq) else 0,
        inserted_block_position=_inserted_block_position(prefix, suffix),
        shared_argument_flow_in_tail=shared_argument_flow_in_tail_features(left, right, prefix),
        sequence_similarity=round(lcs / max_len, 4),
        left_statement_count=len(left_seq),
        right_statement_count=len(right_seq),
    )


def absent_components(left: MemberFeatures, right: MemberFeatures) -> frozenset[str]:
    """Similarity components neither member has evidence for."""
    absent: set[str] = set()
    if not any(left.parameter_features.values()) and not any(right.parameter_features.values()):
        absent.add("parameter")
    if not left.call_counts and not right.call_counts:
        absent.add("call")
    if not left.graph_features and not right.graph_features:
        absent.add("graph")
    return frozenset(absent)


def parameter_use_similarity_features(left: MemberFeatures, right: MemberFeatures) -> float:
    return mean_jaccard_by_key(
        _parameter_feature_sets(left),
        _parameter_feature_sets(right),
    )


def call_multiset_similarity_features(left: MemberFeatures, right: MemberFeatures) -> float:
    return counter_jaccard(left.call_counts, right.call_counts)


def same_call_multiset_features(left: MemberFeatures, right: MemberFeatures) -> bool:
    return bool(left.calls) and left.call_counts == right.call_counts


def graph_similarity_features(left: MemberFeatures, right: MemberFeatures) -> float:
    return jaccard(set(left.graph_features), set(right.graph_features))


def _parameter_feature_sets(features: MemberFeatures) -> dict[str, set[str]]:
    return {role: set(values) for role, values in features.parameter_features.items()}


def tree_node_count(left: OrderedTree | None, right: OrderedTree | None) -> int:
    left_count = ordered_tree_size(left) if left else 0
    right_count = ordered_tree_size(right) if right else 0
    return max(left_count, right_count)


def shared_argument_flow_in_tail_features(
    left: MemberFeatures,
    right: MemberFeatures,
    prefix: int,
) -> bool:
    return bool(
        _tail_arg_reads_from_features(left, prefix) & _tail_arg_reads_from_features(right, prefix)
    )


def _inserted_block_position(prefix: int, suffix: int) -> str:
    if prefix and not suffix:
        return "tail"
    if suffix and not prefix:
        return "head"
    if prefix or suffix:
        return "middle"
    return "none"


def _tail_arg_reads_from_graph(graph: object, prefix: int) -> set[str]:
    if isinstance(graph, DataflowGraph):
        return _tail_arg_reads_from_dataflow(graph, prefix)
    return set()


def _tail_arg_reads_from_features(features: MemberFeatures, prefix: int) -> set[str]:
    if features.statement_arg_reads:
        reads: set[str] = set()
        for index, values in features.statement_arg_reads:
            if index >= prefix:
                reads.update(values)
        return reads
    return _tail_arg_reads_from_graph(features.local_dataflow_graph, prefix)


def _tail_arg_reads_from_dataflow(graph: DataflowGraph, prefix: int) -> set[str]:
    reads: set[str] = set()
    for node in graph.nodes:
        if node.kind != "statement" or not node.id.startswith("STMT"):
            continue
        index = int(node.id.removeprefix("STMT") or 0)
        if index >= prefix:
            reads.update(node.arg_reads)
    return reads


def _tree_size_for_edit(features: MemberFeatures) -> int:
    return features.body_tree_size or max(features.tree_node_count, 0)


def _tree_edit_proxy_similarity(left: MemberFeatures, right: MemberFeatures) -> float:
    if left.body_shape and left.body_shape == right.body_shape:
        return 1.0
    if left.statements or right.statements:
        return jaccard(set(left.aligned_statements), set(right.aligned_statements))
    return 0.0


def _similarity_from_distance(edit_distance: int, node_count: int) -> float:
    if node_count == 0:
        return 1.0
    return round(max(0.0, 1 - edit_distance / node_count), 4)
