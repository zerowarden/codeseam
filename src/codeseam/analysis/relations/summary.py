from __future__ import annotations

from codeseam.analysis.relations.models import (
    ActionKind,
    ActionStatus,
    RefactorAction,
    RefactorActionSummary,
)


def summarize_actions(actions: list[RefactorAction]) -> RefactorActionSummary:
    recommended = [
        action
        for action in actions
        if (action.status or ActionStatus.RECOMMENDED)
        in {ActionStatus.RECOMMENDED, ActionStatus.CONDITIONAL}
    ]
    rejected = [
        action.kind
        for action in actions
        if (action.status or ActionStatus.RECOMMENDED) == ActionStatus.NOT_RECOMMENDED
    ]
    if not recommended and not rejected:
        return RefactorActionSummary()
    primary = recommended[0].kind if recommended else None
    secondary = recommended[1].kind if len(recommended) > 1 else None
    return RefactorActionSummary(
        primary_action=primary,
        secondary_action=secondary,
        not_recommended=tuple(rejected),
        primary_scope=_scope(primary, rejected) if primary else "",
        secondary_scope=_scope(secondary, rejected) if secondary else "",
    )


def _scope(action_kind: ActionKind, rejected: list[ActionKind]) -> str:
    if action_kind is ActionKind.CONSOLIDATE_CLONE:
        if ActionKind.DO_NOT_REFACTOR in rejected:
            return "consolidate exact or renamed subclusters only"
        return "consolidate clone pairs with concrete body evidence"
    scopes = {
        ActionKind.DO_NOT_REFACTOR: (
            "keep repeated code separate because the current duplication is safer"
        ),
        ActionKind.EXTRACT_SMALL_HELPER: (
            "extract a local helper only where the shared operation is concrete"
        ),
        ActionKind.REUSE_EXISTING_HELPER: (
            "replace the local wrapper with an existing helper where the operation is concrete"
        ),
        ActionKind.INSPECT_SHARED_LIFECYCLE: (
            "inspect the repeated workflow before proposing code changes"
        ),
        ActionKind.INTRODUCE_ABSTRACTION: (
            "introduce an abstraction only for stable repeated concepts"
        ),
        ActionKind.RECORD_SHARED_CONCERN: ("record shared concern without merging implementations"),
    }
    return scopes.get(action_kind, "inspect action scope before editing")


__all__ = ["summarize_actions"]
