from __future__ import annotations

from dataclasses import dataclass, field

BOUNDARY_TOKENS = {
    "auth",
    "crypto",
    "fast",
    "latency",
    "perf",
    "sanitize",
    "secret",
    "security",
    "timeout",
}


@dataclass(frozen=True, slots=True)
class StructuralPolicy:
    """Limits for cluster-level structural enrichment before pair scoring."""

    summary_limit: int = field(
        default=5,
        metadata={"doc": "Maximum representative items shown in relation summaries."},
    )
    structural_pair_limit: int = field(
        default=10,
        metadata={
            "doc": "Maximum high-confidence structural duplicate pairs retained per cluster."
        },
    )
    structural_bucket_member_limit: int = field(
        default=32,
        metadata={"doc": "Maximum members allowed in a bounded structural candidate bucket."},
    )
    structural_pair_candidate_limit: int = field(
        default=400,
        metadata={"doc": "Most bucketed candidate pairs scored, by estimated content similarity."},
    )
    max_statement_count: int = field(
        default=8,
        metadata={
            "doc": "Largest compact statement sequence eligible for exact structural matching."
        },
    )
    max_tree_nodes: int = field(
        default=120,
        metadata={"doc": "Largest body-tree node count eligible for tree-edit comparison."},
    )
    name_similarity_threshold: float = field(
        default=0.85,
        metadata={"doc": "Name similarity needed to classify a strong structural duplicate."},
    )
    tree_similarity_threshold: float = field(
        default=0.9,
        metadata={"doc": "Tree similarity needed to classify a strong structural duplicate."},
    )
    min_statement_lcs_length: int = field(
        default=2,
        metadata={"doc": "Minimum aligned statements before LCS is meaningful evidence."},
    )
    min_stable_statement_count: int = field(
        default=2,
        metadata={"doc": "Minimum stable statements before anti-unification is meaningful."},
    )


@dataclass(frozen=True, slots=True)
class TreeEditPolicy:
    """Gates and cost bounds for ordered tree-edit comparisons."""

    graph_threshold: float = field(
        default=0.60,
        metadata={"doc": "Compact dataflow similarity that counts as dataflow agreement."},
    )
    edit_product_limit: int = field(
        default=250_000,
        metadata={
            "doc": "Maximum left_nodes * right_nodes for exact tree edit distance (~50 ms at most)."
        },
    )


@dataclass(frozen=True, slots=True)
class PairPolicy:
    """Pair-level relation scoring thresholds.

    These values decide whether a candidate pair becomes a relation and how
    small special relation families are lifted above generic similarity scores.
    """

    relation_pair_limit: int = field(
        default=20,
        metadata={"doc": "Maximum relation pairs emitted per enriched signature cluster."},
    )
    relatedness_minimum: float = field(
        default=0.35,
        metadata={"doc": "Minimum final relatedness score required to emit a relation pair."},
    )
    parameter_flow_threshold: float = field(
        default=0.85,
        metadata={"doc": "Parameter-use similarity treated as matching argument flow."},
    )
    call_fingerprint_threshold: float = field(
        default=0.65,
        metadata={"doc": "Call multiset similarity treated as meaningful call overlap."},
    )
    min_wrapper_stable_edge_count: int = field(
        default=3,
        metadata={"doc": "Minimum stable prefix+suffix statements for wrapper/core evidence."},
    )
    min_argument_normalization_relatedness: float = field(
        default=0.72,
        metadata={
            "doc": (
                "Relatedness floor for argument-normalization wrappers: pairs that normalize "
                "different inputs before the same downstream operation should not be ranked as "
                "weak merely because their signatures differ."
            )
        },
    )
    min_argument_normalization_refactorability: float = field(
        default=0.68,
        metadata={
            "doc": (
                "Refactorability floor for argument-normalization wrappers when the downstream "
                "operation is shared and the remaining differences are mostly argument binding."
            )
        },
    )
    name_gate_token_similarity_threshold: float = field(
        default=0.5,
        metadata={
            "doc": (
                "Token-overlap threshold before paying for string edit distance in name scoring; "
                "below this, token Jaccard is used as the cheap name score."
            )
        },
    )
    multi_member_threshold: int = field(
        default=2,
        metadata={
            "doc": "Minimum member count that turns pair evidence into a group-level action."
        },
    )
    action_limit: int = field(
        default=5,
        metadata={"doc": "Maximum refactor action candidates retained for a relation family."},
    )


@dataclass(frozen=True, slots=True)
class RelationAssessmentPolicy:
    """Risk and action thresholds used after pair relations have been scored."""

    high_abstraction_cost_threshold: float = field(
        default=0.65,
        metadata={"doc": "Cost score above which extraction is considered high-cost."},
    )
    manageable_parameter_count: int = field(
        default=2,
        metadata={"doc": "Parameter count still considered easy to extract or consolidate."},
    )
    high_parameter_count: int = field(
        default=6,
        metadata={"doc": "Parameter count that usually makes an abstraction cumbersome."},
    )
    parameterized_skeleton_max_abstraction_cost: float = field(
        default=0.25,
        metadata={
            "doc": (
                "Maximum abstraction cost before same-skeleton literal/callee variants stop "
                "emitting direct consolidate-clone action candidates."
            )
        },
    )
    refactorability_high_threshold: float = field(
        default=0.75,
        metadata={"doc": "Refactorability score band boundary for high-confidence editability."},
    )
    refactorability_medium_threshold: float = field(
        default=0.45,
        metadata={"doc": "Refactorability score band boundary for plausible editability."},
    )
    many_parameter_threshold: int = field(
        default=4,
        metadata={"doc": "Member parameter count that contributes an abstraction-risk caveat."},
    )
    min_vocabulary_members: int = field(
        default=2,
        metadata={"doc": "Minimum members needed before vocabulary mismatch is meaningful."},
    )


@dataclass(frozen=True, slots=True)
class ContentPolicy:
    """Content-based candidate generation across signature shapes and sizes."""

    rare_shingle_max_df: int = field(
        default=16,
        metadata={"doc": "Shingles shared by more functions than this are too common to block on."},
    )
    min_statements: int = field(
        default=2,
        metadata={"doc": "One-statement bodies (accessors, delegations) never cross signatures."},
    )
    min_shingles: int = field(
        default=4,
        metadata={"doc": "Functions with fewer structural shingles carry too little content."},
    )
    min_shared_rare_shingles: int = field(
        default=2,
        metadata={"doc": "Rare shingles a pair must share before its overlap is verified."},
    )
    min_jaccard: float = field(
        default=0.55,
        metadata={"doc": "Shingle-set Jaccard a candidate pair needs to become a content edge."},
    )
    neighbor_limit: int = field(
        default=8,
        metadata={"doc": "Most content edges kept per function, by descending Jaccard."},
    )
    component_member_limit: int = field(
        default=12,
        metadata={"doc": "Largest content cluster; bigger families stay as several clusters."},
    )


@dataclass(frozen=True, slots=True)
class BlockPolicy:
    """Shared statement blocks inside otherwise different functions (partial clones)."""

    min_statements: int = field(
        default=4,
        metadata={"doc": "Shortest run of equal top-level statements worth extracting."},
    )
    min_distinct_statements: int = field(
        default=3,
        metadata={"doc": "A run of one repeated statement is a pattern, not a block to extract."},
    )
    min_lines: int = field(
        default=8,
        metadata={"doc": "Fewest source lines the run must span in every occurrence."},
    )
    max_window_df: int = field(
        default=8,
        metadata={"doc": "Statement windows found in more functions than this are boilerplate."},
    )


STRUCTURAL_POLICY = StructuralPolicy()
CONTENT_POLICY = ContentPolicy()
BLOCK_POLICY = BlockPolicy()
TREE_EDIT_POLICY = TreeEditPolicy()
PAIR_POLICY = PairPolicy()
RELATION_ASSESSMENT_POLICY = RelationAssessmentPolicy()

__all__ = [
    "BLOCK_POLICY",
    "BlockPolicy",
    "CONTENT_POLICY",
    "ContentPolicy",
    "BOUNDARY_TOKENS",
    "PAIR_POLICY",
    "RELATION_ASSESSMENT_POLICY",
    "STRUCTURAL_POLICY",
    "TREE_EDIT_POLICY",
    "PairPolicy",
    "RelationAssessmentPolicy",
    "StructuralPolicy",
    "TreeEditPolicy",
]
