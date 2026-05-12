from __future__ import annotations

from codeseam.analysis import (
    AbstractionRisk,
    CallsitePattern,
    CandidateGenerationSummary,
    Cluster,
    ClusterEnrichment,
    ClusterMember,
    Clusters,
    ClusterSummary,
    OrderedTree,
    PolicyConstant,
    PolicyConstantCluster,
    SignatureAnalysis,
    SignatureCore,
    StructuralSubcluster,
    signature_analysis_from_core,
)
from codeseam.output.serializers.relations import (
    action_payload,
    context_classification_payload,
    member_ref_payload,
    relation_pair_payload,
)
from codeseam.output.serializers.trees import tree_payload
from codeseam.platform import Json


def signature_record_payload(
    signature: SignatureAnalysis | SignatureCore,
    *,
    body_tree: OrderedTree | None = None,
) -> Json:
    analysis = (
        signature
        if isinstance(signature, SignatureAnalysis)
        else signature_analysis_from_core(signature)
    )
    core = analysis.core
    features = analysis.features
    output = analysis.output
    payload: Json = {
        "language": core.language,
        "language_family": core.language_family.value,
        "adapter": core.adapter.value,
        "file": core.file,
        "symbol": core.symbol,
        "normalized_symbol": core.normalized_symbol,
        "container": core.container,
        "start_line": core.start_line,
        "end_line": core.end_line,
        "role": core.role,
        "type_source": core.type_source.value,
        "parameters": core.parameters,
        "return_type": core.return_type,
        "raw_signature": output.raw_signature,
        "canonical_shape": core.canonical_shape,
        "shape_hash": core.shape_hash,
        "body_line_count": core.body_line_count,
        "body_shape": output.body_shape,
        "body_shape_hash": core.body_shape_hash,
        "body_tree": None,
        "body_tree_node_count": core.body_tree_node_count,
        "statement_sequence": core.statement_sequence,
        "call_tokens": core.call_tokens,
        "parameter_default_roles": dict(features.parameter_default_roles),
        "graph_features": sorted(features.graph_features),
        "literal_shapes": sorted(features.literal_shapes),
        "receiver_shapes": sorted(features.receiver_shapes),
        "parameter_features": {key: sorted(values) for key, values in features.parameter_features},
        "normalization_transform_tokens": sorted(features.normalization_transform_tokens),
        "statement_arg_reads": features.statement_arg_reads,
        "control_context_vector": core.control_context_vector,
        "caveats": output.caveats,
        "non_claims": output.non_claims,
        "schema_version": output.schema_version,
        "signature_id": core.signature_id,
        "function_id": core.function_id,
        "semantic_roles": getattr(core, "semantic_roles", ()),
        "semantic_role_reasons": getattr(core, "semantic_role_reasons", ()),
        "is_callable_factory": output.is_callable_factory,
        "evidence_kinds": output.evidence_kinds,
        "callsite_patterns": [
            callsite_pattern_payload(pattern) for pattern in output.callsite_patterns
        ],
    }
    if body_tree:
        payload["body_tree"] = tree_payload(body_tree)
    return payload


def signature_clusters_payload(clusters: Clusters) -> Json:
    return {
        "schema_version": clusters.schema_version,
        "clusters": [signature_cluster_payload(cluster) for cluster in clusters.clusters],
        "same_language_cluster_count": clusters.same_language_cluster_count,
        "adapter_wrapper_cluster_count": clusters.adapter_wrapper_cluster_count,
        "analogous_cluster_count": clusters.analogous_cluster_count,
        "policy_constant_clusters": [
            policy_constant_cluster_payload(cluster)
            for cluster in clusters.policy_constant_clusters
        ],
    }


def signature_cluster_payload(cluster: Cluster) -> Json:
    payload: Json = {
        "schema_version": cluster.schema_version,
        "cluster_id": cluster.cluster_id,
        "language": cluster.language,
        "shape_hash": cluster.shape_hash,
        "canonical_shape": cluster.canonical_shape,
        "member_count": cluster.member_count,
        "members": [cluster_member_payload(member) for member in cluster.members],
        "overlaps": {key: list(values) for key, values in cluster.overlaps.items()},
        "review_relevance": cluster.review_relevance,
        "priority_hint": cluster.priority_hint,
        "non_claims": list(cluster.non_claims),
        "cluster_scope": cluster.cluster_scope,
        "languages": list(cluster.languages),
        "language_count": cluster.language_count,
        "language_families": [family.value for family in cluster.language_families],
        "language_family_count": cluster.language_family_count,
        "adapters": [adapter.value for adapter in cluster.adapters],
        "adapter_count": cluster.adapter_count,
        "min_extraction_confidence": cluster.min_extraction_confidence.value,
        "normalization_level": cluster.normalization_level.value,
    }
    if cluster.enrichment:
        payload.update(cluster_enrichment_payload(cluster.enrichment))
    return payload


def cluster_member_payload(member: ClusterMember) -> Json:
    signature = member.signature
    payload: Json = {
        "signature_id": signature.signature_id,
        "function_id": signature.function_id,
        "file": signature.file,
        "symbol": signature.symbol,
        "normalized_symbol": signature.normalized_symbol,
        "start_line": signature.start_line,
        "end_line": signature.end_line,
        "role": signature.role,
        "body_shape_hash": signature.body_shape_hash,
        "body_tree_node_count": signature.body_tree_node_count,
        "body_line_count": signature.body_line_count,
        "statement_sequence": signature.statement_sequence,
        "call_tokens": signature.call_tokens,
        "control_context_vector": signature.control_context_vector,
        "parameters": signature.parameters,
        "return_type": signature.return_type,
    }
    if member.language:
        payload["language"] = member.language
        payload["language_family"] = member.language_family.value
        payload["adapter"] = member.adapter.value
    return payload


def cluster_enrichment_payload(enrichment: ClusterEnrichment) -> Json:
    return {
        "enrichment_schema_version": "codeseam.signature_cluster_enrichment.v1",
        "schema_versions": {
            "cluster": "codeseam.signature_cluster.v1",
            "enrichment": "codeseam.signature_cluster_enrichment.v1",
        },
        "cluster_summary": cluster_summary_payload(enrichment.cluster_summary),
        "confidence": enrichment.confidence,
        "cluster_confidence": enrichment.confidence,
        "evidence_kinds": list(enrichment.evidence_kinds),
        "callable_factory_members": [
            member_ref_payload(member) for member in enrichment.callable_factory_members
        ],
        "callsite_patterns": [
            callsite_pattern_payload(pattern)
            for pattern in enrichment.callsite_patterns
            if isinstance(pattern, CallsitePattern)
        ],
        "structural_relation_pairs": [
            relation_pair_payload(pair) for pair in enrichment.structural_relation_pairs
        ],
        "structural_duplicate_pairs": [
            relation_pair_payload(pair) for pair in enrichment.structural_duplicate_pairs
        ],
        "structural_subclusters": [
            structural_subcluster_payload(subcluster)
            for subcluster in enrichment.structural_subclusters
        ],
        "candidate_generation": candidate_generation_payload(enrichment.candidate_generation),
        "refactor_action_candidates": [
            action_payload(action) for action in enrichment.refactor_action_candidates
        ],
        "refactor_action_summary": {
            "primary_action": (
                enrichment.refactor_action_summary.primary_action.value
                if enrichment.refactor_action_summary.primary_action
                else None
            ),
            "secondary_action": (
                enrichment.refactor_action_summary.secondary_action.value
                if enrichment.refactor_action_summary.secondary_action
                else None
            ),
            "not_recommended": [
                action.value for action in enrichment.refactor_action_summary.not_recommended
            ],
            **(
                {"primary_scope": enrichment.refactor_action_summary.primary_scope}
                if enrichment.refactor_action_summary.primary_scope
                else {}
            ),
            **(
                {"secondary_scope": enrichment.refactor_action_summary.secondary_scope}
                if enrichment.refactor_action_summary.secondary_scope
                else {}
            ),
        },
        "abstraction_kind": enrichment.abstraction_kind,
        "abstraction_risks": [
            abstraction_risk_payload(risk) for risk in enrichment.abstraction_risks
        ],
        "context_classifications": [
            context_classification_payload(classification)
            for classification in enrichment.context_classifications
        ],
    }


def callsite_pattern_payload(pattern: CallsitePattern) -> Json:
    payload: Json = {
        "kind": pattern.kind,
        "symbol": pattern.symbol,
        "file": pattern.file,
        "line": pattern.line,
    }
    if pattern.variable:
        payload["variable"] = pattern.variable
    return payload


def abstraction_risk_payload(risk: object) -> Json:
    if isinstance(risk, AbstractionRisk):
        payload: Json = {"kind": risk.kind}
        if risk.message:
            payload["message"] = risk.message
        return payload
    return {"kind": str(risk)}


def cluster_summary_payload(summary: ClusterSummary) -> Json:
    return {
        "member_count": summary.member_count,
        "representative_files": list(summary.representative_files),
        "representative_symbols": list(summary.representative_symbols),
        "line_ranges": [
            {
                "file": line.file,
                "start_line": line.start_line,
                "end_line": line.end_line,
            }
            for line in summary.line_ranges
        ],
        "evidence_kinds": list(summary.evidence_kinds),
        "confidence": summary.confidence,
    }


def candidate_generation_payload(summary: CandidateGenerationSummary) -> Json:
    return {
        "methods": list(summary.methods),
        "implemented_scope": summary.implemented_scope,
        "member_count": summary.member_count,
        "eligible_member_count": summary.eligible_member_count,
        "candidate_pair_count": summary.candidate_pair_count,
        "comparison_stats": summary.comparison_stats,
        "candidate_pair_limit": summary.candidate_pair_limit,
        "bucket_member_limit": summary.bucket_member_limit,
        "max_statement_count": summary.max_statement_count,
        "max_tree_node_count": summary.max_tree_node_count,
        "shape_hash_count": summary.shape_hash_count,
        "body_hash_count": summary.body_hash_count,
        "name_token_bucket_count": summary.name_token_bucket_count,
        "call_fingerprint_token_count": summary.call_fingerprint_token_count,
    }


def structural_subcluster_payload(subcluster: StructuralSubcluster) -> Json:
    return {
        "subcluster_id": subcluster.subcluster_id,
        "relation_kind": subcluster.relation_kind.value,
        "clone_family": subcluster.clone_family.value,
        "clone_type": subcluster.clone_type.value,
        "recommended_action": subcluster.recommended_action.value,
        "refactorability_kind": subcluster.refactorability_kind.value,
        "pair_count": subcluster.pair_count,
        "members": [member_ref_payload(member) for member in subcluster.members],
        "scores": {
            "max_relatedness": subcluster.scores.max_relatedness,
            "mean_relatedness": subcluster.scores.mean_relatedness,
            "max_refactorability": subcluster.scores.max_refactorability,
            "mean_refactorability": subcluster.scores.mean_refactorability,
        },
    }


def policy_constant_cluster_payload(cluster: PolicyConstantCluster) -> Json:
    return {
        "schema_version": cluster.schema_version,
        "cluster_id": cluster.cluster_id,
        "language": cluster.language,
        "shape_hash": cluster.shape_hash,
        "canonical_shape": cluster.canonical_shape,
        "member_count": cluster.member_count,
        "members": [policy_constant_payload(member) for member in cluster.members],
        "review_relevance": cluster.review_relevance,
        "priority_hint": cluster.priority_hint,
        "confidence": cluster.confidence,
        "evidence_kinds": list(cluster.evidence_kinds),
        "abstraction_kind": cluster.abstraction_kind,
        "refactor_action_candidates": [
            action_payload(action) for action in cluster.refactor_action_candidates
        ],
        "refactor_action_summary": {
            "primary_action": (
                cluster.refactor_action_summary.primary_action.value
                if cluster.refactor_action_summary.primary_action
                else None
            ),
            "secondary_action": (
                cluster.refactor_action_summary.secondary_action.value
                if cluster.refactor_action_summary.secondary_action
                else None
            ),
            "not_recommended": [
                action.value for action in cluster.refactor_action_summary.not_recommended
            ],
        },
        "non_claims": list(cluster.non_claims),
    }


def policy_constant_payload(constant: PolicyConstant) -> Json:
    return {
        "schema_version": "codeseam.policy_constant.v1",
        "language": constant.language,
        "file": constant.file,
        "symbol": constant.symbol,
        "normalized_symbol": constant.normalized_symbol,
        "start_line": constant.start_line,
        "end_line": constant.end_line,
        "role": constant.role,
        "literal_kind": constant.literal_kind,
        "literal_shape_hash": constant.literal_shape_hash,
        "literal_preview": constant.literal_preview,
    }


__all__ = [
    "policy_constant_payload",
    "signature_clusters_payload",
    "signature_record_payload",
]
