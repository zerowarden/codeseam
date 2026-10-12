from __future__ import annotations

import hashlib
import os
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from codeseam.analysis import AssessmentPolicy
from codeseam.analysis.assessment.policy import ASSESSMENT_SECTION
from codeseam.platform import (
    INIT_CONFIG_RESOURCE,
    ConfigError,
    FileSelection,
    Json,
    config_candidates,
    default_config,
    dumps_jsonable_stable,
    is_count,
    merge_into,
    project_file,
    resource_text,
    set_nested,
    write_atomic,
)
from codeseam.platform.storage import validate_storage_root
from codeseam.semantics import SemanticMode, semantic_mode_from_config

AUTO_REPO_ROOT = "auto"


@dataclass(frozen=True, slots=True)
class _Setting:
    expected: str
    accepts: Callable[[object], bool]


def _is_str(value: object) -> bool:
    return isinstance(value, str)


def _is_bool(value: object) -> bool:
    return isinstance(value, bool)


def _is_patterns(value: object) -> bool:
    return isinstance(value, str) or (
        isinstance(value, list) and all(isinstance(item, str) for item in value)
    )


TEXT = _Setting("a string", _is_str)
FLAG = _Setting("true or false", _is_bool)
COUNT = _Setting("a non-negative integer", is_count)
PATTERNS = _Setting("a glob pattern or a list of glob patterns", _is_patterns)
MODE = _Setting(
    f"one of {', '.join(mode.value for mode in SemanticMode)}",
    lambda value: value in {mode.value for mode in SemanticMode},
)
# Every accepted setting. `[assessment]` is checked by `AssessmentPolicy`.
SETTINGS: dict[str, dict[str, _Setting]] = {
    "project": {"repo_root": TEXT},
    "output": {"root": TEXT},
    "selection": {"include": PATTERNS, "exclude": PATTERNS},
    "agent_summary": {"max_targets": COUNT},
    "cache": {"enabled": FLAG, "path": TEXT},
    "relations": {"split_test": FLAG},
    "semantics": {"mode": MODE, "trust_project_code": FLAG},
}
ENV_SETTINGS: dict[str, tuple[str, str]] = {
    "CODESEAM_REPO_ROOT": ("project", "repo_root"),
    "CODESEAM_OUTPUT_ROOT": ("output", "root"),
    "CODESEAM_CACHE_ENABLED": ("cache", "enabled"),
    "CODESEAM_CACHE_PATH": ("cache", "path"),
}


@dataclass(frozen=True)
class Config:
    """Validated, immutable settings for one run.

    Each source (defaults, config files, `.codeseamignore`, environment, CLI)
    is checked on its own before merging, so errors name where a bad value
    came from. `config_hash` covers the merged settings.
    """

    repo_root: Path
    output_root: Path
    cache_path: Path
    cache_enabled: bool
    split_test: bool
    selection: FileSelection
    agent_summary_max_targets: int
    semantic_mode: SemanticMode
    trust_project_code: bool
    assessment: AssessmentPolicy
    config_hash: str
    sources: tuple[str, ...]


def load_config(
    repo_root: Path | None = None,
    cli_overrides: Json | None = None,
) -> Config:
    root = (repo_root or Path.cwd()).resolve()
    merged = default_config()
    sources: list[str] = ["defaults"]

    for path in config_candidates(root):
        if path.exists():
            source = str(path.relative_to(root))
            merge_into(merged, _checked(_read_toml(path), source))
            sources.append(source)

    ignore_patterns = _read_codeseamignore(project_file(root, "ignore"))
    if ignore_patterns:
        set_nested(merged, ("selection", "exclude"), [*_exclude(merged), *ignore_patterns])
        sources.append(".codeseamignore")

    if env_config := _env_config(os.environ):
        merge_into(merged, _checked(env_config, "environment"))
        sources.append("environment")

    if cli_overrides and (cleaned := _clean_overrides(cli_overrides)):
        merge_into(merged, _checked(cleaned, "cli"))
        sources.append("cli")

    config = _config(_scan_root(root, merged), merged, tuple(sources))
    if config.semantic_mode is SemanticMode.REQUIRED and not config.trust_project_code:
        raise ConfigError(
            "semantics.mode = required starts the compiler worker, which runs code from "
            "the analysed repository; set semantics.trust_project_code = true to allow it"
        )
    validate_storage_root(config.repo_root, config.output_root, label="output.root")
    validate_storage_root(config.repo_root, config.cache_path, label="cache.path")
    return config


def materialize_init_config(path: Path) -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(path, resource_text(INIT_CONFIG_RESOURCE))
    return True


def _config(root: Path, merged: Json, sources: tuple[str, ...]) -> Config:
    def setting(section: str, key: str) -> object:
        return cast(Json, merged[section])[key]

    try:
        assessment = AssessmentPolicy.from_config(merged)
    except ValueError as exc:
        raise ConfigError(f"Invalid assessment setting: {exc}") from exc
    return Config(
        repo_root=root,
        output_root=_under(root, str(setting("output", "root"))),
        cache_path=_under(root, str(setting("cache", "path"))),
        cache_enabled=cast(bool, setting("cache", "enabled")),
        split_test=cast(bool, setting("relations", "split_test")),
        selection=FileSelection(
            include=_pattern_tuple(setting("selection", "include")),
            exclude=_exclude(merged),
        ),
        agent_summary_max_targets=cast(int, setting("agent_summary", "max_targets")),
        semantic_mode=semantic_mode_from_config(merged),
        trust_project_code=cast(bool, setting("semantics", "trust_project_code")),
        assessment=assessment,
        config_hash=_config_hash(merged),
        sources=sources,
    )


def _checked(layer: Json, source: str) -> Json:
    """Reject unknown sections and keys, and values of the wrong type."""

    for section, values in layer.items():
        if section == ASSESSMENT_SECTION:
            try:
                AssessmentPolicy.from_config({ASSESSMENT_SECTION: values})
            except ValueError as exc:
                raise ConfigError(f"{source}: invalid assessment setting: {exc}") from exc
            continue
        settings = SETTINGS.get(section)
        if settings is None:
            raise ConfigError(f"{source}: unknown section [{section}]")
        if not isinstance(values, Mapping):
            raise ConfigError(f"{source}: [{section}] must be a table, not {values!r}")
        for key, value in cast(Mapping[str, object], values).items():
            setting = settings.get(key)
            if setting is None:
                raise ConfigError(f"{source}: unknown setting {section}.{key}")
            if not setting.accepts(value):
                raise ConfigError(
                    f"{source}: {section}.{key} must be {setting.expected}, not {value!r}"
                )
    return layer


def _scan_root(root: Path, merged: Json) -> Path:
    """`project.repo_root` may narrow the scan to a subdirectory, never leave it."""

    value = str(cast(Json, merged["project"])["repo_root"])
    if value == AUTO_REPO_ROOT:
        return root
    scan_root = _under(root, value).resolve()
    if scan_root != root and root not in scan_root.parents:
        raise ConfigError(f"project.repo_root must be inside {root}: {value}")
    return scan_root


def _under(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _read_toml(path: Path) -> Json:
    try:
        with path.open("rb") as file:
            return cast(Json, tomllib.load(file))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Invalid TOML in {path}: {exc}") from exc


def _pattern_tuple(value: object) -> tuple[str, ...]:
    return (value,) if isinstance(value, str) else tuple(cast(list[str], value))


def _exclude(merged: Json) -> tuple[str, ...]:
    return _pattern_tuple(cast(Json, merged["selection"])["exclude"])


def _read_codeseamignore(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [
        line
        for raw_line in path.read_text(encoding="utf-8").splitlines()
        if (line := raw_line.strip()) and not line.startswith("#")
    ]


def _env_config(environ: Mapping[str, str]) -> Json:
    config: Json = {}
    for env_name, (section, key) in ENV_SETTINGS.items():
        if (value := environ.get(env_name)) is not None:
            flag = SETTINGS[section][key] is FLAG
            set_nested(config, (section, key), _env_flag(value) if flag else value)
    return config


def _env_flag(value: str) -> bool | str:
    lowered = value.lower()
    return lowered == "true" if lowered in {"true", "false"} else value


def _clean_overrides(overrides: Json) -> Json:
    cleaned: Json = {}
    for dotted_key, value in overrides.items():
        if value is not None:
            set_nested(cleaned, tuple(dotted_key.split(".")), value)
    return cleaned


def _config_hash(config: Json) -> str:
    payload = dumps_jsonable_stable(config)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
