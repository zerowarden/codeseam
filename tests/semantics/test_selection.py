from __future__ import annotations

from typing import Any, cast

from codeseam.semantics import (
    SemanticCandidate,
    SemanticMode,
    SemanticProject,
    build_semantic_enrichment_requests,
)


def test_semantic_selection_skips_off_mode() -> None:
    requests = build_semantic_enrichment_requests(
        repo_root="/repo",
        mode=SemanticMode.OFF,
        projects=(_project(),),
        candidates=(_candidate(),),
    )

    assert requests == ()


def test_semantic_selection_ignores_languages_without_project() -> None:
    requests = build_semantic_enrichment_requests(
        repo_root="/repo",
        mode=SemanticMode.AUTO,
        projects=(_project(languages=("TypeScript",)),),
        candidates=(
            _candidate(language="Python", signature_id="sig_py", relative_path="src/app.py"),
        ),
    )

    assert requests == ()


def test_semantic_selection_groups_candidates_by_project() -> None:
    requests = build_semantic_enrichment_requests(
        repo_root="/repo",
        mode=SemanticMode.AUTO,
        projects=(
            _project(
                project_id="tsconfig-app",
                project_cache_key="sha256:app",
                config_path="apps/app/tsconfig.json",
                paths=("apps/app/src/a.ts",),
            ),
            _project(
                project_id="tsconfig-lib",
                project_cache_key="sha256:lib",
                config_path="packages/lib/tsconfig.json",
                paths=("packages/lib/src/b.ts",),
            ),
        ),
        candidates=(
            _candidate(signature_id="sig_a", relative_path="apps/app/src/a.ts"),
            _candidate(signature_id="sig_b", relative_path="packages/lib/src/b.ts"),
        ),
    )

    assert [request.project_cache_key for request in requests] == ["sha256:app", "sha256:lib"]
    assert [request.items[0].signature_id for request in requests] == ["sig_a", "sig_b"]


def test_semantic_selection_matches_lowercase_adapter_language_labels() -> None:
    requests = build_semantic_enrichment_requests(
        repo_root="/repo",
        mode=SemanticMode.AUTO,
        projects=(_project(languages=("TypeScript",)),),
        candidates=(
            _candidate(language="typescript", signature_id="sig_ts", relative_path="src/app.ts"),
        ),
    )

    assert requests[0].items[0].signature_id == "sig_ts"


def test_semantic_selection_is_candidate_bounded_and_deterministic() -> None:
    requests = build_semantic_enrichment_requests(
        repo_root="/repo",
        mode=SemanticMode.AUTO,
        projects=(_project(),),
        candidates=(
            _candidate(signature_id="sig_3", start_line=30),
            _candidate(signature_id="sig_1", start_line=10),
            _candidate(signature_id="sig_2", start_line=20),
        ),
        max_items_per_request=2,
    )

    assert len(requests) == 1
    assert [item.signature_id for item in requests[0].items] == ["sig_1", "sig_2"]


def test_semantic_selection_keeps_ambiguous_role_candidates() -> None:
    requests = build_semantic_enrichment_requests(
        repo_root="/repo",
        mode=SemanticMode.AUTO,
        projects=(_project(),),
        candidates=(
            _candidate(
                signature_id="sig_decl",
                semantic_roles=("declaration_boundary",),
                has_relation_evidence=False,
            ),
        ),
    )

    assert requests[0].items[0].signature_id == "sig_decl"


def test_semantic_selection_skips_low_value_observation_candidates() -> None:
    requests = build_semantic_enrichment_requests(
        repo_root="/repo",
        mode=SemanticMode.AUTO,
        projects=(_project(),),
        candidates=(
            _candidate(
                signature_id="sig_low",
                semantic_roles=(),
                has_relation_evidence=False,
                has_body_evidence=False,
                has_call_evidence=False,
            ),
        ),
    )

    assert requests == ()


def _project(
    *,
    project_id: str = "tsconfig",
    project_cache_key: str = "sha256:project",
    config_path: str = "tsconfig.json",
    languages: tuple[str, ...] = ("TypeScript", "TSX", "JavaScript", "JSX"),
    paths: tuple[str, ...] = (),
) -> SemanticProject:
    return SemanticProject(
        project_id=project_id,
        language="TypeScript",
        languages=languages,
        project_cache_key=project_cache_key,
        config_path=config_path,
        paths=paths,
    )


def _candidate(**updates: object) -> SemanticCandidate:
    values: dict[str, object] = {
        "signature_id": "sig_1",
        "language": "TypeScript",
        "relative_path": "src/app.ts",
        "start_line": 1,
        "end_line": 3,
        "callable_kind": "function",
        "symbol_hint": "run",
        "semantic_roles": (),
        "has_relation_evidence": True,
        "has_body_evidence": True,
        "has_call_evidence": False,
    }
    values.update(updates)
    if "start_line" in updates and "end_line" not in updates:
        values["end_line"] = int(cast(int, updates["start_line"])) + 2
    return SemanticCandidate(
        **cast(Any, values),
    )
