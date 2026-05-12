from __future__ import annotations

from codeseam.analysis.assessment.cluster import Cluster
from codeseam.analysis.findings.models import FindingLocation


def signature_locations(cluster: Cluster) -> list[FindingLocation]:
    return [
        FindingLocation(
            file=member.signature.file,
            start_line=member.signature.start_line,
            end_line=member.signature.end_line,
            source="signature",
            kind="signature_shape",
            symbol=member.signature.symbol,
        )
        for member in cluster.members
    ]


def line_span(findings: list[FindingLocation]) -> int:
    return sum(max(1, finding.end_line - finding.start_line + 1) for finding in findings)


__all__ = [
    "signature_locations",
    "line_span",
]
