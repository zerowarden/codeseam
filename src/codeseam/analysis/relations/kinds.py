from __future__ import annotations

from enum import StrEnum


class AbstractionKind(StrEnum):
    """High-level abstraction families used to describe a finding's shape."""

    COMPILER_FACTORY = "compiler_factory"
    EXTRACT_HELPER = "extract_helper"
    MOVE_MODULE = "move_module"
    PIPELINE_TEMPLATE = "pipeline_template"
    REGISTRY_DISPATCH = "registry_dispatch"
    TRACK_ONLY = "track_only"


class EvidenceKind(StrEnum):
    ARGUMENT_NORMALIZATION_WRAPPER = "argument_normalization_wrapper"
    CALLABLE_FACTORY = "callable_factory"
    CALLSITE_CACHED = "callsite_cached"
    CALLSITE_IMMEDIATE = "callsite_immediate"
    CALLSITE_PIPELINE = "callsite_pipeline"
    CALLSITE_REGISTERED = "callsite_registered"
    CALLSITE_STORED_REUSE = "callsite_stored_reuse"
    INTRA_FUNCTION_DUPLICATE = "intra_function_duplicate"
    POLICY_CONSTANT_DUPLICATE = "policy_constant_duplicate"
    SIGNATURE_SHAPE_CLUSTER = "signature_shape_cluster"
    STRUCTURAL_DUPLICATE = "structural_duplicate"


CALLSITE_EVIDENCE_KINDS = (
    EvidenceKind.CALLSITE_IMMEDIATE,
    EvidenceKind.CALLSITE_STORED_REUSE,
    EvidenceKind.CALLSITE_REGISTERED,
    EvidenceKind.CALLSITE_PIPELINE,
    EvidenceKind.CALLSITE_CACHED,
)


class RiskKind(StrEnum):
    BOUNDARY_MISMATCH = "boundary_mismatch"
    ERROR_SEMANTICS_MISMATCH = "error_semantics_mismatch"
    LAYER_MISMATCH = "layer_mismatch"
    MANY_PARAMETERS = "many_parameters"
    SMALL_COMMONALITY = "small_commonality"
    TEST_SEMANTICS_MISMATCH = "test_semantics_mismatch"
    VOCABULARY_MISMATCH = "vocabulary_mismatch"


class RelationKind(StrEnum):
    NONE = "none"
    BODY_IDENTICAL = "body_identical"
    BODY_PARAMETERIZED = "body_parameterized"
    ARGUMENT_NORMALIZATION_WRAPPER = "argument_normalization_wrapper"
    SAME_SKELETON_DIFFERENT_LITERALS = "same_skeleton_different_literals"
    SAME_SKELETON_DIFFERENT_CALLEES = "same_skeleton_different_callees"
    COMMON_PREFIX_DIVERGENT_TAIL = "common_prefix_divergent_tail"
    COMMON_SUFFIX_DIVERGENT_SETUP = "common_suffix_divergent_setup"
    COMMON_WRAPPER_DIFFERENT_CORE = "common_wrapper_different_core"
    SAME_CORE_DIFFERENT_WRAPPER = "same_core_different_wrapper"
    SAME_ARGUMENT_FLOW_DIFFERENT_CONTROL = "same_argument_flow_different_control"
    SAME_CALL_SET_DIFFERENT_ORDER = "same_call_set_different_order"


CLEAN_CLONE_RELATIONS = frozenset((RelationKind.BODY_IDENTICAL, RelationKind.BODY_PARAMETERIZED))
PARAMETERIZED_SKELETON_RELATIONS = frozenset(
    (
        RelationKind.SAME_SKELETON_DIFFERENT_LITERALS,
        RelationKind.SAME_SKELETON_DIFFERENT_CALLEES,
    )
)


class DeltaKind(StrEnum):
    ARGUMENT_FLOW = "ARGUMENT_FLOW_DELTA"
    ARGUMENT_NORMALIZATION = "ARGUMENT_NORMALIZATION_DELTA"
    CALLEE_NAME = "CALLEE_NAME_DELTA"
    CONTROL_FLOW = "CONTROL_FLOW_DELTA"
    DEFAULT_ARGUMENT = "DEFAULT_ARGUMENT_DELTA"
    ERROR_HANDLING = "ERROR_HANDLING_DELTA"
    EXTRA_ASSIGNMENT = "EXTRA_ASSIGNMENT_DELTA"
    EXTRA_CONTEXT_MANAGER = "EXTRA_CONTEXT_MANAGER_DELTA"
    EXTRA_LOCAL_TEMPORARY = "EXTRA_LOCAL_TEMPORARY_DELTA"
    EXTRA_TERMINAL_CALL = "EXTRA_TERMINAL_CALL_DELTA"
    LITERAL_VALUE = "LITERAL_VALUE_DELTA"
    LOOP = "LOOP_DELTA"
    RECEIVER_SHAPE = "RECEIVER_SHAPE_DELTA"
    RETURN_VALUE = "RETURN_VALUE_DELTA"


class CloneClass(StrEnum):
    TYPE_1_EXACT = "type_1_exact"
    TYPE_2_PARAMETERIZED = "type_2_parameterized"
    TYPE_3_NEAR_MISS = "type_3_near_miss"
    CONTRACT_ANALOGY = "contract_analogy"
    SIGNATURE_SIGNAL_ONLY = "signature_signal_only"


class ActionKind(StrEnum):
    """Review action ladder emitted by relation and scoring stages.

    The values describe the safest next action for a finding, not the exact
    implementation technique.
    """

    OBSERVE = "observe"
    RECORD_SHARED_CONCERN = "record_shared_concern"
    INSPECT_SHARED_LIFECYCLE = "inspect_shared_lifecycle"
    EXTRACT_SMALL_HELPER = "extract_small_helper"
    REUSE_EXISTING_HELPER = "reuse_existing_helper"
    CONSOLIDATE_CLONE = "consolidate_clone"
    INTRODUCE_ABSTRACTION = "introduce_abstraction"
    DO_NOT_REFACTOR = "do_not_refactor"


class ActionStatus(StrEnum):
    RECOMMENDED = "recommended"
    CONDITIONAL = "conditional"
    NOT_RECOMMENDED = "not_recommended"


class ScoreBand(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    TRACK_ONLY = "track_only"


__all__ = [
    "AbstractionKind",
    "ActionKind",
    "ActionStatus",
    "CALLSITE_EVIDENCE_KINDS",
    "CloneClass",
    "CLEAN_CLONE_RELATIONS",
    "DeltaKind",
    "EvidenceKind",
    "PARAMETERIZED_SKELETON_RELATIONS",
    "RelationKind",
    "RiskKind",
    "ScoreBand",
]
