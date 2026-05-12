from __future__ import annotations

from dataclasses import dataclass

from codeseam.platform import Json, json_int


@dataclass(frozen=True, slots=True)
class RepositorySummary:
    files_analysed: int
    files_skipped: int
    functions_seen: int


def repository_summary(summary: Json) -> RepositorySummary:
    return RepositorySummary(
        files_analysed=json_int(summary.get("files_analysed")),
        files_skipped=json_int(summary.get("files_skipped")),
        functions_seen=json_int(summary.get("functions_seen")),
    )


def repository_summary_lines(summary: Json) -> list[str]:
    counts = repository_summary(summary)
    return [
        f"Files analysed: {counts.files_analysed:,}",
        f"Files skipped: {counts.files_skipped:,}",
        f"Functions seen: {counts.functions_seen:,}",
    ]


__all__ = ["RepositorySummary", "repository_summary", "repository_summary_lines"]
