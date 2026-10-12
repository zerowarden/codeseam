from __future__ import annotations

from collections.abc import Sequence

from codeseam.analysis import Clusters, SignatureAnalysis
from codeseam.output.serializers.signatures import (
    signature_clusters_payload,
    signature_record_payload,
)
from codeseam.platform import OutputPaths, write_jsonable_atomic, write_jsonl_jsonable_atomic


def write_signature_artifacts(
    paths: OutputPaths, records: Sequence[SignatureAnalysis], clusters: Clusters
) -> None:
    write_jsonl_jsonable_atomic(
        paths.artifact("signatures"),
        (signature_record_payload(record) for record in records),
    )
    write_jsonable_atomic(
        paths.artifact("signature_clusters"),
        signature_clusters_payload(clusters),
        pretty=True,
    )
