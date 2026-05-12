from __future__ import annotations

import argparse
import cProfile
import shutil
import time
from pathlib import Path

from codeseam.adapters.repository.filesystem import DEFAULT_EXCLUDES, explain_file_selection
from codeseam.adapters.repository.root import detect_repo_root
from codeseam.cli.constants import DEFAULT_TARGET_LIMIT
from codeseam.cli.exit_codes import OK, THRESHOLD_BREACHED
from codeseam.cli.models import CliOutput, OutputOptions, cli_output
from codeseam.cli.options import output_options
from codeseam.cli.output import console_for
from codeseam.cli.progress import progress_for
from codeseam.config import Config, load_config
from codeseam.output.serializers.analysis import AnalysisPayloadSummary, analysis_result_payload
from codeseam.pipeline.analyze import (
    AnalysisPipelineRequest,
    analysis_exit_code,
    run_analysis_pipeline,
)
from codeseam.platform import (
    ConfigError,
    Json,
    OutputPaths,
    RepositoryContextError,
    as_json_object,
    text_list,
)
from codeseam.profiling import ProfileOutput, ProfileSource, collect_profile_summary


def profile_command(args: argparse.Namespace) -> CliOutput:
    cache_mode = str(getattr(args, "cache_mode", "warm") or "warm")
    if cache_mode == "cold":
        _clear_profile_cache(args)
    analyze_args = argparse.Namespace(
        base_ref=None,
        no_progress=True,
        output=None,
        path=None,
        profile=None,
        progress="never",
        quiet=True,
        repo_root=args.repo_root,
        strict=False,
        target_limit=DEFAULT_TARGET_LIMIT,
        timings=False,
        verbose=False,
        color="auto",
        ci=False,
        debug=False,
        semantic_mode=None,
        format=None,
        include=None,
        exclude=None,
        show_exclusions=False,
        explain_files=False,
    )
    profiler = cProfile.Profile()
    started = time.perf_counter()
    result = profiler.runcall(_analyze_command, analyze_args, include_profile_source=True)
    elapsed = time.perf_counter() - started
    payload = result.data.get("result", {})
    timings = payload.get("timings", {}) if isinstance(payload, dict) else {}
    cache_stats = timings.get("cache", {}) if isinstance(timings, dict) else {}
    profile_source = result.data["profile_source"]
    # Keep profile aggregation outside cProfile so sorting/ranking work does not
    # appear in the reported analysis hot path.
    return cli_output(
        "profile_result",
        profile=ProfileOutput(
            profiler=profiler,
            summary=collect_profile_summary(profile_source, profiler),
            elapsed_seconds=elapsed,
            cache_mode=cache_mode,
            cache_stats=cache_stats if isinstance(cache_stats, dict) else {},
            sort=str(args.sort),
            limit=int(args.limit),
        ),
        exit_code=OK,
    )


def _clear_profile_cache(args: argparse.Namespace) -> None:
    repo_root_arg = getattr(args, "repo_root", None)
    config = load_config(detect_repo_root(_explicit_repo_root(repo_root_arg)))
    cache_root = config.cache_path()
    if cache_root.exists():
        shutil.rmtree(cache_root)


def analyze_command(args: argparse.Namespace) -> CliOutput:
    return _analyze_command(args, include_profile_source=False)


def _analyze_command(args: argparse.Namespace, *, include_profile_source: bool) -> CliOutput:
    options = output_options(args)
    if options.output_format == "sarif" and not options.ci:
        raise ConfigError("Output format is not implemented yet: sarif")
    config = _config_from_args(args)
    if file_selection_output := _file_selection_output(args, config, options):
        return file_selection_output
    paths = OutputPaths(config.path("output", "root"))
    with progress_for(options, console_for(options)) as progress:
        run = run_analysis_pipeline(
            AnalysisPipelineRequest(
                config=config,
                paths=paths,
                progress=progress,
                base_ref=args.base_ref,
                debug=bool(getattr(args, "debug", False)),
            ),
        )
    payload = {
        "result": analysis_result_payload(
            paths=paths,
            summary=AnalysisPayloadSummary(
                files_analysed=run.selected_file_count,
                files_skipped=run.skipped_file_count,
                functions_seen=run.function_count,
                languages=tuple(
                    sorted(
                        {
                            run.repository_facts.languages_by_path[path]
                            for path in run.repository_facts.selected_paths
                        }
                    )
                ),
            ),
            report_artifacts=run.report_artifacts,
            timings=run.timings,
        ),
        "options": options,
    }
    if include_profile_source:
        payload["profile_source"] = ProfileSource(
            selected_file_count=run.selected_file_count,
            function_count=run.function_count,
            signature_artifacts=run.signature_artifacts,
        )
    return cli_output(
        "analyze_result",
        **payload,
        exit_code=analysis_exit_code(
            run.report_artifacts,
            threshold_exit=THRESHOLD_BREACHED,
            ok_exit=OK,
        ),
    )


def _file_selection_output(
    args: argparse.Namespace,
    config: Config,
    options: OutputOptions,
) -> CliOutput | None:
    if getattr(args, "show_exclusions", False):
        return cli_output(
            "default_exclusions",
            patterns=_default_exclusions(),
            options=options,
        )
    if getattr(args, "explain_files", False):
        selection = as_json_object(config.data.get("selection"))
        return cli_output(
            "file_explanation",
            explanation=explain_file_selection(config.repo_root, selection),
            options=options,
        )
    return None


def _config_from_args(args: argparse.Namespace) -> Config:
    path_arg = getattr(args, "path", None)
    repo_root_arg = getattr(args, "repo_root", None)
    if path_arg and repo_root_arg:
        raise ConfigError("Use either analyze [path] or --repo-root, not both")
    explicit = _explicit_repo_root(path_arg or repo_root_arg)
    repo_root = detect_repo_root(explicit)
    overrides: Json = {}
    include = _patterns_arg(args, "include")
    exclude = _patterns_arg(args, "exclude")
    if include:
        overrides["selection.include"] = include
    semantic_mode = getattr(args, "semantic_mode", None)
    if semantic_mode:
        overrides["semantics.mode"] = str(semantic_mode)
    if exclude:
        base_config = load_config(repo_root, overrides)
        overrides["selection.exclude"] = [
            *text_list(as_json_object(base_config.data.get("selection")).get("exclude")),
            *exclude,
        ]
    return load_config(repo_root, overrides)


def _patterns_arg(args: argparse.Namespace, name: str) -> list[str]:
    value = getattr(args, name, None)
    return [str(item) for item in value] if isinstance(value, list) else []


def _default_exclusions() -> list[str]:
    return list(DEFAULT_EXCLUDES)


def _explicit_repo_root(value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if not path.exists():
        raise RepositoryContextError(f"Repository path does not exist: {path}")
    if not path.is_dir():
        raise RepositoryContextError(f"Repository path is not a directory: {path}")
    return path


__all__ = ["analyze_command", "profile_command"]
