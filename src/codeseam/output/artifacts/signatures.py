from __future__ import annotations

from typing import TYPE_CHECKING

from codeseam.output.serializers.signatures import (
    signature_clusters_payload,
    signature_record_payload,
)
from codeseam.platform import OutputPaths, write_jsonable_atomic, write_jsonl_jsonable_atomic

if TYPE_CHECKING:
    from codeseam.pipeline.signatures import SignatureArtifacts


def write_signature_artifacts(paths: OutputPaths, artifacts: SignatureArtifacts) -> None:
    write_jsonl_jsonable_atomic(
        paths.artifact("signatures"),
        (signature_record_payload(record) for record in artifacts.records),
    )
    write_jsonable_atomic(
        paths.artifact("signature_clusters"),
        signature_clusters_payload(artifacts.clusters),
        pretty=True,
    )
