from __future__ import annotations

from codeseam.analysis import ReviewTier
from codeseam.platform import Json, as_json_object, json_int
from codeseam.version import package_version

CI_ARTIFACT_PATHS = (
    ".codeseam/reports/ci/codeseam-report.json",
    ".codeseam/reports/ci/codeseam-report.sarif",
    ".codeseam/reports/ci/codeseam-summary.md",
)


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
            "baseline": None,
            "failing_targets": failing_targets,
            "exit_code": 1 if failing_targets else 0,
        },
        "artifacts": list(CI_ARTIFACT_PATHS),
    }
    if include_timings:
        payload["timings"] = as_json_object(result.get("timings"))
    return payload


def ci_sarif_payload(payload: Json) -> Json:
    return {
        "version": "2.1.0",
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "codeseam",
                        "version": payload.get("codeseam_version", ""),
                        "rules": [],
                    }
                },
                "results": [],
                "properties": {
                    "failing_targets": as_json_object(payload.get("ci")).get("failing_targets", 0),
                },
            }
        ],
    }


__all__ = ["CI_ARTIFACT_PATHS", "ci_payload", "ci_sarif_payload"]
