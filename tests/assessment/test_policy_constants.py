"""Policy constants: identical copies are edits; drift and scattered names need a person."""

from __future__ import annotations

from pathlib import Path

import pytest

from codeseam.adapters.languages import LanguageAnalysisContext, default_language_registry
from codeseam.analysis import (
    AssessmentPolicy,
    PolicyConstant,
    PolicyConstantMatch,
    assess_target,
    build_policy_constant_clusters,
)
from codeseam.analysis.assessment.definitions import FindingActionStatus
from codeseam.analysis.findings.drafts import build_policy_constant_drafts

ORDER = '{"high": 0, "medium": 1, "low": 2, "info": 3}'


def _constants(tmp_path: Path, sources: dict[str, str]) -> list[PolicyConstant]:
    adapter = default_language_registry().adapter_for_language("Python")
    assert adapter is not None
    constants: list[PolicyConstant] = []
    for name, source in sources.items():
        path = tmp_path / name
        path.write_text(source, encoding="utf-8")
        context = LanguageAnalysisContext(path, name, "source", "Python")
        constants.extend(adapter.extract_analysis(context).policy_constants)
    return constants


@pytest.mark.parametrize(
    ("sources", "expected"),
    [
        (
            {"a.py": f"PRIORITY_ORDER = {ORDER}\n", "b.py": f"PRIORITY_ORDER = {ORDER}\n"},
            [(PolicyConstantMatch.IDENTICAL, FindingActionStatus.RECOMMENDED_EDIT)],
        ),
        (
            {
                "a.py": f"PRIORITY_ORDER = {ORDER}\n",
                "b.py": 'PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2, "debug": 4}\n',
            },
            [(PolicyConstantMatch.DRIFTED, FindingActionStatus.RECORD_SHARED_CONCERN)],
        ),
        (
            {
                "a.py": 'DEFAULT_FIELDS = ("id", "name")\n',
                "b.py": 'DEFAULT_FIELDS = ("path", "size", "mode")\n',
            },
            [],
        ),
        (
            {"a.py": f"PRIORITY_ORDER = {ORDER}\n", "b.py": f"SEVERITY_RANK = {ORDER}\n"},
            [(PolicyConstantMatch.SCATTERED, FindingActionStatus.RECORD_SHARED_CONCERN)],
        ),
        (
            {"a.py": f"PRIORITY_ORDER = {ORDER}\nPRIORITY_ORDER = {ORDER[:-1]}, 'x': 9}}\n"},
            [],
        ),
    ],
    ids=["identical", "drifted", "unrelated-same-name", "scattered", "same-file-reassignment"],
)
def test_policy_constants_report_copies_drift_and_scattered_rules(
    tmp_path: Path,
    sources: dict[str, str],
    expected: list[tuple[PolicyConstantMatch, FindingActionStatus]],
) -> None:
    clusters = build_policy_constant_clusters(_constants(tmp_path, sources))
    findings = [
        assess_target(draft, roles_by_path={}, policy=AssessmentPolicy())
        for draft in build_policy_constant_drafts(tuple(clusters))
    ]

    assert [
        (cluster.match, finding.action_status)
        for cluster, finding in zip(clusters, findings, strict=True)
    ] == expected
