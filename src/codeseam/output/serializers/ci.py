from __future__ import annotations

import os

from codeseam.analysis import ReviewTier
from codeseam.platform import Json, as_json_object, json_int
from codeseam.version import package_version


def ci_payload(result: Json, *, include_timings: bool = False) -> Json:
    findings = as_json_object(result.get("findings"))
    failing_targets = (
        json_int(findings.get(ReviewTier.RECOMMENDED_EDIT)) if isinstance(findings, dict) else 0
    )
    payload: Json = {
        "schema_version": "codeseam.ci_report.v1",
        "codeseam_version": package_version(),
        "summary": as_json_object(result.get("summary")),
        "findings": findings,
        "ci": {
            "enabled": True,
            "fail_on": "recommended_edit",
            "fail_scope": "all_targets",
            "failing_targets": failing_targets,
            "exit_code": 1 if failing_targets else 0,
        },
        "artifacts": [
            os.path.relpath(str(path))
            for key in ("analysis_path", "agent_summary_path", "human_summary_path")
            if (path := as_json_object(result.get("reports")).get(key))
        ],
    }
    if include_timings:
        payload["timings"] = as_json_object(result.get("timings"))
    return payload


__all__ = ["ci_payload"]
