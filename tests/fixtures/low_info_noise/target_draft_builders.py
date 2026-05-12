from __future__ import annotations


def build_signature_drafts(signature_clusters: list[Json]) -> list[FindingDraft]:
    targets = []
    for cluster in signature_clusters:
        if not isinstance(cluster, dict):
            continue
        files = dedupe(
            text(member.get("file"))
            for member in as_json_objects(cluster.get("members"))
        )
        cluster_id = text(cluster.get("cluster_id"))
        evidence_kinds = text_list(cluster.get("evidence_kinds"))
        abstraction_risks = as_json_objects(cluster.get("abstraction_risks"))
        relation_pairs = as_json_objects(cluster.get("structural_relation_pairs"))
        action_summary = cluster.get("refactor_action_summary", {})
        if not isinstance(action_summary, dict):
            action_summary = {}
        targets.append(
            FindingDraft(
                target_type=TARGET_TYPE_SIGNATURE_SHAPE,
                title=_signature_title(cluster),
                severity="medium",
                confidence=float(cluster.get("confidence", 0.0)),
                files=files,
                locations=_signature_locations(cluster),
                metrics={
                    "cluster_id": cluster_id,
                    "evidence_kind_count": len(evidence_kinds),
                    "risk_count": len(abstraction_risks),
                    "relation_pair_count": len(relation_pairs),
                    "action_count": int(action_summary.get("count", 0)),
                },
            )
        )
    return targets


def build_policy_constant_drafts(clusters: list[Json]) -> list[FindingDraft]:
    targets = []
    for cluster in clusters:
        members = as_json_objects(cluster.get("members"))
        files = dedupe(text(member.get("file")) for member in members)
        cluster_id = text(cluster.get("cluster_id"))
        evidence_kinds = text_list(cluster.get("evidence_kinds"))
        actions = as_json_objects(cluster.get("refactor_action_candidates"))
        summary = cluster.get("refactor_action_summary", {})
        if not isinstance(summary, dict):
            summary = {}
        targets.append(
            FindingDraft(
                target_type=TARGET_TYPE_SIGNATURE_SHAPE,
                title=f"Duplicated policy constant {_policy_constant_symbol(cluster)}",
                severity="high",
                confidence=float(cluster.get("confidence", POLICY_CONSTANT_CONFIDENCE)),
                files=files,
                locations=_policy_constant_locations(members),
                metrics={
                    "cluster_id": cluster_id,
                    "evidence_kind_count": len(evidence_kinds),
                    "policy_constant_duplicate_count": 1,
                    "action_count": len(actions),
                    "summary_count": int(summary.get("count", 0)),
                },
            )
        )
    return targets
