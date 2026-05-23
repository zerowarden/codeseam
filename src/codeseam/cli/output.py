from __future__ import annotations

import io
import pstats
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.console import Console, Group
from rich.text import Text

from codeseam.analysis import ReviewTier
from codeseam.cli.ci import render_ci_summary
from codeseam.cli.constants import REVIEW_TIER_LABELS
from codeseam.cli.explain import ExplainRenderOptions, render_explain
from codeseam.cli.models import CliOutput, OutputOptions
from codeseam.cli.repository_summary import repository_summary
from codeseam.output.serializers.ci import ci_payload, ci_sarif_payload
from codeseam.output.serializers.finding_buckets import is_agent_summary_target
from codeseam.output.serializers.titles import (
    display_action_title,
    display_reason_label,
    display_sentence,
)
from codeseam.platform import (
    Json,
    as_json_object,
    as_json_objects,
    display_path,
    dumps_jsonable_stable,
    json_float,
    json_int,
    plural_noun,
    single_line,
)
from codeseam.profiling import ClusterProfileRow, ProfileOutput
from codeseam.version import package_version

SECONDS_PER_MINUTE = 60
LOCAL_REVIEW_TARGET_LIMIT = 10
LOCAL_REVIEW_MEMBER_LIMIT = 3
LOCAL_REVIEW_TIER_STYLES = {
    ReviewTier.RECOMMENDED_EDIT: "bold red",
    ReviewTier.REVIEW_CANDIDATE: "bold orange3",
}


@dataclass(frozen=True)
class DataRenderer:
    renderer: Callable[..., None]
    keys: tuple[str, ...]
    defaults: dict[str, object] | None = None

    def __call__(self, output: CliOutput) -> None:
        args = []
        for key in self.keys:
            if key in output.data:
                args.append(output.data[key])
            elif self.defaults and key in self.defaults:
                args.append(self.defaults[key])
            else:
                raise KeyError(key)
        self.renderer(*args)


class ProfileRenderer:
    def __call__(self, output: CliOutput) -> None:
        profile = output.data["profile"]
        if not isinstance(profile, ProfileOutput):
            raise TypeError("profile_result requires ProfileOutput")
        _render_profile_result(profile)


def render_cli_output(output: CliOutput) -> None:
    try:
        renderer = _OUTPUT_RENDERERS[output.kind]
    except KeyError as exc:
        raise ValueError(f"Unknown CLI output kind: {output.kind}") from exc
    renderer(output)


def _render_none() -> None:
    return


def _render_help(parser: Any, stderr: object = False) -> None:
    _write_plain(str(parser.format_help()), stderr=bool(stderr))


def _render_parser_error(parser: Any, message: object) -> None:
    _write_plain(f"{parser.format_help()}\nerror: {message}\n", stderr=True)


def _render_error_output(message: object, prefix: object = "error") -> None:
    _render_error(str(message), prefix=str(prefix))


def _render_cancelled() -> None:
    _write_plain("cancelled by user\n", stderr=True)


def _render_json_output(payload: Json, pretty: object = True) -> None:
    _write_json_payload(payload, pretty=bool(pretty))


def _render_init_output(
    root: Path,
    report_root: Path,
    created: list[Path],
    existing: list[Path],
) -> None:
    _render_init_result(
        root=root,
        report_root=report_root,
        created=created,
        existing=existing,
    )


def _render_explain_not_found(target_id: object) -> None:
    _write_plain(f"target not found: {target_id}\n", stderr=True)


def _render_explain_result(
    item: Json,
    options: ExplainRenderOptions,
    source_lines: list[str] | None,
) -> None:
    _write_plain(render_explain(item, options, source_lines=source_lines))


def console_for(options: OutputOptions) -> Console:
    return Console(
        force_terminal=True if options.color == "always" else None,
        color_system="256" if options.color == "always" else "auto",
        no_color=options.color == "never",
    )


def render_analyze_result(result: Json, options: OutputOptions) -> None:
    if options.ci:
        match options.output_format:
            case "json":
                _write_text(render_ci_json(result, options), options.output)
            case "ndjson":
                _write_text(render_ci_ndjson(result, options), options.output)
            case "sarif":
                _write_text(render_sarif(result, options), options.output)
            case _:
                render_ci_analyze_result(result, options)
        return
    match options.output_format:
        case "json":
            _write_text(render_json(result, options), options.output)
        case "ndjson":
            _write_text(render_ndjson(result, options), options.output)
        case "sarif":
            _write_text(render_sarif(result, options), options.output)
        case _:
            render_default_analyze_result(result, options)


def render_default_exclusions(patterns: list[str], options: OutputOptions) -> None:
    lines = [Text("Default exclusions:"), *[Text(f"- {pattern}") for pattern in patterns]]
    _write_or_print(Group(*lines), "\n".join(line.plain for line in lines) + "\n", options)


def render_file_explanation(explanation: Json, options: OutputOptions) -> None:
    groups = explanation.get("top_skipped_groups", [])
    lines = [
        Text(f"Analysed: {json_int(explanation.get('analysed')):,} files"),
        Text(f"Skipped: {json_int(explanation.get('skipped')):,} files"),
        Text(),
        Text("Top skipped groups:"),
    ]
    if isinstance(groups, list) and groups:
        lines.extend(
            Text(f"- {item.get('group')}: {json_int(item.get('count')):,}")
            for item in groups
            if isinstance(item, dict)
        )
    else:
        lines.append(Text("- none: 0"))
    _write_or_print(Group(*lines), "\n".join(line.plain for line in lines) + "\n", options)


def _render_error(message: str, *, prefix: str = "error") -> None:
    _write_plain(f"{prefix}: {message}\n", stderr=True)


def _write_json_payload(payload: Json, *, pretty: bool = True) -> None:
    sys.stdout.write(dumps_jsonable_stable(payload, pretty=pretty) + "\n")


def _render_profile_result(profile: ProfileOutput) -> None:
    stream = io.StringIO()
    summary = profile.summary
    stream.write(f"analysis_seconds={profile.elapsed_seconds:.3f}\n")
    stream.write(f"cache_mode={profile.cache_mode}\n")
    stream.write("profile_summary:\n")
    stream.write(f"  selected_file_count={summary.selected_file_count}\n")
    stream.write(f"  function_count={summary.function_count}\n")
    stream.write(f"  signature_count={summary.signature_count}\n")
    stream.write(f"  cluster_count={summary.cluster_count}\n")
    stream.write(f"  candidate_pair_count={summary.candidate_pair_count}\n")
    stream.write(f"  relation_pair_count={summary.relation_pair_count}\n")
    stream.write(f"  operation_features_count={summary.operation_features_count}\n")
    stream.write(f"  call_facts_count={summary.call_facts_count}\n")
    _write_cluster_rows(
        stream,
        "top_clusters_by_enrichment_ms",
        summary.top_clusters_by_enrichment_ms,
    )
    _write_cluster_rows(
        stream,
        "top_clusters_by_candidate_pairs",
        summary.top_clusters_by_candidate_pairs,
    )
    _write_cluster_rows(
        stream,
        "top_clusters_by_relation_pairs",
        summary.top_clusters_by_relation_pairs,
    )
    _write_cluster_rows(
        stream,
        "top_clusters_by_cache_misses",
        summary.top_clusters_by_cache_misses,
    )
    _write_cluster_rows(
        stream,
        "top_clusters_by_survival_rate",
        summary.top_clusters_by_survival_rate,
    )
    _write_cache_blob_stats(stream, profile.cache_stats)
    pstats.Stats(profile.profiler, stream=stream).strip_dirs().sort_stats(profile.sort).print_stats(
        max(1, profile.limit)
    )
    _write_text(stream.getvalue(), None)


def _write_cluster_rows(
    stream: io.StringIO,
    title: str,
    rows: tuple[ClusterProfileRow, ...],
) -> None:
    stream.write(f"{title}:\n")
    if not rows:
        stream.write("  none\n")
        return
    for row in rows:
        stream.write(
            "  "
            f"{row.cluster_id} shape={row.shape} members={row.members} "
            f"candidates={row.candidates} relations={row.relations} "
            f"enrichment_ms={row.enrichment_ms} candidate_ms={row.candidate_ms} "
            f"relation_ms={row.relation_ms} cache_hit/miss={row.cache_hits}/{row.cache_misses} "
            f"scope={row.scope} survival_rate={row.survival_rate:.4f} "
            f"top_directories={','.join(row.top_directories) or '-'} "
            f"roles={','.join(row.top_roles) or '-'}\n"
        )


def _write_cache_blob_stats(stream: io.StringIO, cache_stats: object) -> None:
    if not isinstance(cache_stats, dict):
        return
    namespaces = cache_stats.get("namespaces", {})
    if not isinstance(namespaces, dict):
        return
    rows = [
        (str(namespace), stats)
        for namespace, stats in namespaces.items()
        if isinstance(stats, dict) and stats.get("blob_load_count")
    ]
    if not rows:
        return
    stream.write("cache_blob_load_stats:\n")
    for namespace, stats in sorted(
        rows,
        key=lambda item: float(item[1].get("blob_load_ms", 0.0)),
        reverse=True,
    ):
        stream.write(
            "  "
            f"{namespace}: count={stats.get('blob_load_count', 0)} "
            f"bytes={stats.get('blob_load_bytes', 0)} "
            f"total_ms={stats.get('blob_load_ms', 0)} "
            f"avg_ms={stats.get('blob_load_avg_ms', 0)} "
            f"max_ms={stats.get('blob_load_max_ms', 0)}\n"
        )


def _render_init_result(
    *,
    root: Path,
    report_root: Path,
    created: list[Path],
    existing: list[Path],
) -> None:
    lines = ["Initialised Codeseam for this repository.", ""]
    if created:
        lines.extend(["Created:", *[f"- {display_path(root, path)}" for path in created], ""])
    else:
        lines.extend(["Created:", "- nothing", ""])
    if existing:
        lines.extend(
            [
                "Already existed:",
                *[f"- {display_path(root, path)}" for path in existing],
                "",
            ]
        )
    lines.extend(
        [
            "Codeseam will write reports to:",
            f"- {display_path(root, report_root)}/",
            "",
            "Next:",
            "  codeseam analyze",
        ]
    )
    _write_plain("\n".join(lines) + "\n")


def _render_validation_result(issues: list[Any]) -> None:
    if issues:
        for issue in issues:
            _write_plain(f"{issue.artifact}: {issue.message}\n", stderr=True)
        return
    _write_plain("schema validation passed\n")


_OUTPUT_RENDERERS: dict[str, Callable[[CliOutput], None]] = {
    "none": DataRenderer(_render_none, ()),
    "help": DataRenderer(_render_help, ("parser", "stderr"), {"stderr": False}),
    "parser_error": DataRenderer(_render_parser_error, ("parser", "message")),
    "error": DataRenderer(_render_error_output, ("message", "prefix"), {"prefix": "error"}),
    "cancelled": DataRenderer(_render_cancelled, ()),
    "profile_result": ProfileRenderer(),
    "analyze_result": DataRenderer(render_analyze_result, ("result", "options")),
    "default_exclusions": DataRenderer(render_default_exclusions, ("patterns", "options")),
    "file_explanation": DataRenderer(render_file_explanation, ("explanation", "options")),
    "json_payload": DataRenderer(_render_json_output, ("payload", "pretty"), {"pretty": True}),
    "init_result": DataRenderer(
        _render_init_output,
        ("root", "report_root", "created", "existing"),
    ),
    "explain_result": DataRenderer(_render_explain_result, ("item", "options", "source_lines")),
    "explain_not_found": DataRenderer(_render_explain_not_found, ("target_id",)),
    "validation_result": DataRenderer(_render_validation_result, ("issues",)),
}


def render_json(result: Json, options: OutputOptions) -> str:
    return _json_document(_machine_payload(result, options))


def render_ndjson(result: Json, options: OutputOptions) -> str:
    payload = _machine_payload(result, options)
    targets = as_json_objects(payload.get("targets"))
    return _ndjson(
        [
            {
                "type": "summary",
                "schema_version": payload["schema_version"],
                "codeseam_version": payload["codeseam_version"],
                "summary": payload["summary"],
                "findings": payload["findings"],
                "threshold_breached": payload["threshold_breached"],
                "target_count": payload["target_count"],
                "target_limit": payload["target_limit"],
                "targets_truncated": payload["targets_truncated"],
            },
            *({"type": "target", **target} for target in targets),
        ]
    )


def render_ci_json(result: Json, options: OutputOptions) -> str:
    return _json_document(ci_payload(result, include_timings=options.timings))


def render_ci_ndjson(result: Json, options: OutputOptions) -> str:
    payload = ci_payload(result, include_timings=options.timings)
    return _ndjson(
        [
            {
                "type": "summary",
                "schema_version": payload["schema_version"],
                "codeseam_version": payload["codeseam_version"],
                "summary": payload["summary"],
                "findings": payload["findings"],
                "ci": payload["ci"],
            }
        ]
    )


def _json_document(payload: Json) -> str:
    return dumps_jsonable_stable(payload, pretty=True) + "\n"


def _ndjson(records: list[Json]) -> str:
    return "".join(dumps_jsonable_stable(record) + "\n" for record in records)


def render_sarif(result: Json, options: OutputOptions) -> str:
    payload = ci_payload(result, include_timings=options.timings)
    return _json_document(ci_sarif_payload(payload))


def render_default_analyze_result(result: Json, options: OutputOptions) -> None:
    if options.quiet:
        return
    console = console_for(options)
    summary = as_json_object(result.get("summary"))
    findings = as_json_object(result.get("findings"))
    timings = as_json_object(result.get("timings"))
    lines: list[Text] = [
        Text(_analysis_summary_line(summary, timings)),
        Text(_language_summary_line(summary)),
        Text(_function_summary_line(summary, findings)),
        Text(),
        Text("Analysis:"),
        *_finding_lines(findings),
        Text(),
    ]
    candidate_lines = _top_review_candidate_lines(result.get("targets"))
    if candidate_lines:
        lines.extend([*candidate_lines, Text()])
    if options.verbose:
        reports = as_json_object(result.get("reports"))
        lines.extend((Text(), Text(f"Artifacts: {reports.get('artifact_root', '')}")))
    if options.timings:
        lines.extend(
            (
                Text(),
                Text(f"Elapsed: {timings.get('elapsed_seconds', 0)}s"),
                _cache_timing_line(timings.get("cache")),
            )
        )
    console.print(Group(*lines))


def render_ci_analyze_result(result: Json, options: OutputOptions) -> None:
    if options.quiet:
        return
    _write_plain(
        render_ci_summary(
            ci_payload(result, include_timings=options.timings),
            result.get("targets"),
        )
    )


def _finding_line(count: object, label: str, count_style: str) -> Text:
    line = Text()
    line.append(f"{json_int(count):>3}", style=count_style)
    line.append(f"  {label}")
    return line


def _finding_lines(findings: Json) -> list[Text]:
    return [
        _finding_line(
            findings[ReviewTier.RECOMMENDED_EDIT],
            REVIEW_TIER_LABELS[ReviewTier.RECOMMENDED_EDIT],
            "bold red",
        ),
        _finding_line(
            findings[ReviewTier.REVIEW_CANDIDATE],
            REVIEW_TIER_LABELS[ReviewTier.REVIEW_CANDIDATE],
            "orange3",
        ),
        _finding_line(
            findings[ReviewTier.MAINTENANCE_NOTE],
            REVIEW_TIER_LABELS[ReviewTier.MAINTENANCE_NOTE],
            "",
        ),
    ]


def _top_review_candidate_lines(targets: object) -> list[Text]:
    top_targets = _local_review_targets(targets)[:LOCAL_REVIEW_TARGET_LIMIT]
    if not top_targets:
        return []
    lines = [Text("Top review required:", style="bold")]
    for target in top_targets:
        review_tier = _local_review_tier(target)
        target_id = str(target.get("id", ""))
        title = str(target.get("title", "")).strip()
        reason = display_sentence(target.get("reason") or "review supporting evidence")
        heading = Text()
        heading.append(
            REVIEW_TIER_LABELS[review_tier],
            style=LOCAL_REVIEW_TIER_STYLES[review_tier],
        )
        heading.append("  ")
        heading.append(target_id, style="bold")
        heading.append(f"  {title}".rstrip())
        lines.extend(
            [
                heading,
                Text(f"   {display_reason_label(target)}: {reason}"),
                Text(
                    "   Action: "
                    f"{_recommended_action(target)}; "
                    f"maintenance payoff: {_assessment_band(target, 'maintenance_payoff')}"
                ),
                *_local_member_lines(target.get("members")),
                Text(),
            ]
        )
    return lines[:-1]


def _local_member_lines(members: object) -> list[Text]:
    if not isinstance(members, list):
        return []
    lines = [
        _local_member_line(member)
        for member in members[:LOCAL_REVIEW_MEMBER_LIMIT]
        if isinstance(member, dict)
    ]
    return [line for line in lines if line.plain.strip(" -")]


def _local_member_line(member: Json) -> Text:
    location, symbol = _local_member_ref(member)
    line = Text("   - ", no_wrap=True)
    line.append(location, style="cyan")
    if symbol:
        line.append(f"::{symbol}")
    return line


def _local_member_ref(member: Json) -> tuple[str, str]:
    path = single_line(member.get("path"))
    start = json_int(member.get("start_line"))
    end = json_int(member.get("end_line"))
    symbol = single_line(member.get("symbol"))
    if start and end and start != end:
        location = f"{path}:{start}-{end}"
    elif start:
        location = f"{path}:{start}"
    else:
        location = path
    return location, symbol


def _recommended_action(target: Json) -> str:
    action = single_line(target.get("primary_action"))
    if action:
        return display_action_title(action)
    recommendation = target.get("action_recommendation")
    if isinstance(recommendation, dict):
        return display_action_title(single_line(recommendation.get("action")))
    return display_action_title("observe")


def _assessment_band(target: Json, key: str) -> str:
    bands = target.get("assessment_bands")
    if isinstance(bands, dict):
        band = single_line(bands.get(key))
        if band:
            return band
    return "unknown"


def _local_review_targets(targets: object) -> list[Json]:
    surfaced_targets = [
        target for target in as_json_objects(targets) if is_agent_summary_target(target)
    ]
    return sorted(surfaced_targets, key=_local_target_key)


def _local_target_key(target: Json) -> tuple[int, float, float, str]:
    recommended_rank = 0 if _local_review_tier(target) is ReviewTier.RECOMMENDED_EDIT else 1
    return (
        recommended_rank,
        -json_float(target.get("review_score")),
        -json_float(target.get("confidence")),
        str(target.get("id", "")),
    )


def _local_review_tier(target: Json) -> ReviewTier:
    value = target.get("review_tier")
    if isinstance(value, ReviewTier):
        return value
    if isinstance(value, str):
        try:
            return ReviewTier(value)
        except ValueError:
            pass
    return ReviewTier.OBSERVATION


def _analysis_summary_line(summary: Json, timings: Json) -> str:
    counts = repository_summary(summary)
    return (
        "Analyzed "
        f"{counts.files_analysed} files "
        f"({counts.files_skipped} skipped) in "
        f"{_duration_label(timings['elapsed_seconds'])}."
    )


def _function_summary_line(summary: Json, findings: Json) -> str:
    observations = json_int(findings.get(ReviewTier.OBSERVATION))
    return (
        f"Discovered {json_int(summary.get('functions_seen')):,} functions. "
        f"Made {observations:,} {plural_noun(observations, 'observation')}."
    )


def _language_summary_line(summary: Json) -> str:
    languages = summary.get("languages")
    if not isinstance(languages, list) or not languages:
        return "Languages detected: unknown"
    return "Languages detected: " + ", ".join(
        _language_display_name(language) for language in languages if isinstance(language, str)
    )


def _language_display_name(language: str) -> str:
    return {
        "javascript": "JavaScript",
        "typescript": "TypeScript",
    }.get(language.lower(), language.capitalize())


def _cache_timing_line(cache: object) -> Text:
    if not isinstance(cache, dict):
        return Text("Cache: unavailable")
    hits = json_int(cache.get("hits"))
    misses = json_int(cache.get("misses"))
    sets = json_int(cache.get("sets"))
    hit_rate = cache.get("hit_rate")
    percent = f"{float(hit_rate) * 100:.1f}%" if isinstance(hit_rate, int | float) else "n/a"
    return Text(f"Cache: {hits} hits, {misses} misses, {sets} writes, hit rate {percent}")


def _machine_payload(result: Json, options: OutputOptions) -> Json:
    targets = as_json_objects(result.get("targets"))
    limit = options.target_limit
    limited = targets[:limit] if limit else []
    payload: Json = {
        "schema_version": "1.0",
        "codeseam_version": package_version(),
        "summary": as_json_object(result.get("summary")),
        "findings": as_json_object(result.get("findings")),
        "threshold_breached": result.get("threshold_breached", False),
        "target_count": len(targets),
        "target_limit": limit,
        "targets_truncated": bool(limit and len(targets) > limit),
        "targets": limited,
    }
    if options.timings:
        payload["timings"] = as_json_object(result.get("timings"))
    return payload


def _write_text(text: str, path: Path | None) -> None:
    if path is None:
        sys.stdout.write(text)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_plain(text: str, *, stderr: bool = False) -> None:
    Console(file=sys.stderr if stderr else sys.stdout, force_terminal=False, no_color=True).print(
        Text(text),
        end="",
    )


def _write_or_print(renderable: Group, text: str, options: OutputOptions) -> None:
    if options.output:
        _write_text(text, options.output)
    else:
        console_for(options).print(renderable)


def _duration_label(seconds: object) -> str:
    value = float(seconds) if isinstance(seconds, int | float) else 0.0
    if value < SECONDS_PER_MINUTE:
        return f"{value:.3f}s"
    count = max(1, round(value / SECONDS_PER_MINUTE))
    unit = "m" if count == 1 else "m"
    return f"{count} {unit}"


__all__ = [
    "console_for",
    "render_cli_output",
    "render_analyze_result",
    "render_default_exclusions",
    "render_file_explanation",
]
