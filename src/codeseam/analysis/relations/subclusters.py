from __future__ import annotations

from codeseam.analysis.assessment.cluster import StructuralSubcluster, SubclusterScores
from codeseam.analysis.relations.clones import clone_metadata, default_action
from codeseam.analysis.relations.models import MemberRef, RelationKind, RelationPair
from codeseam.analysis.relations.scoring import refactorability_kind


def structural_subclusters(relation_pairs: list[RelationPair]) -> list[StructuralSubcluster]:
    clusters = []
    relation_kinds = sorted({pair.relation_kind for pair in relation_pairs if pair})
    for index, relation_kind in enumerate(relation_kinds, 1):
        pairs = [pair for pair in relation_pairs if pair.relation_kind == relation_kind]
        clusters.append(_subcluster(index, relation_kind, pairs))
    return clusters


def subcluster_members(pairs: list[RelationPair]) -> list[MemberRef]:
    by_key = {}
    for pair in pairs:
        for member in (pair.left, pair.right):
            key = (member.file, str(member.start_line), member.symbol)
            by_key[key] = member
    return [by_key[key] for key in sorted(by_key)]


def _subcluster(
    index: int,
    relation_kind: RelationKind,
    pairs: list[RelationPair],
) -> StructuralSubcluster:
    relatedness = [pair.scores.relatedness for pair in pairs]
    refactorability = [pair.scores.refactorability for pair in pairs]
    abstraction_cost = [pair.scores.abstraction_cost for pair in pairs]
    clone_type = clone_metadata(relation_kind)[0]
    return StructuralSubcluster(
        subcluster_id=f"sc_{index:04d}",
        relation_kind=relation_kind,
        clone_family=clone_type,
        clone_type=clone_type,
        recommended_action=default_action(
            relation_kind,
            clone_type,
            max(refactorability),
            max(abstraction_cost),
        ),
        refactorability_kind=refactorability_kind(max(refactorability)),
        pair_count=len(pairs),
        members=tuple(subcluster_members(pairs)),
        scores=SubclusterScores(
            max_relatedness=round(max(relatedness), 4),
            mean_relatedness=round(sum(relatedness) / len(relatedness), 4),
            max_refactorability=round(max(refactorability), 4),
            mean_refactorability=round(sum(refactorability) / len(refactorability), 4),
        ),
    )
