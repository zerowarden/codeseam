from __future__ import annotations

import hashlib
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from codeseam.platform import (
    INIT_CONFIG_RESOURCE,
    ConfigError,
    Json,
    config_candidates,
    default_config,
    dumps_jsonable_stable,
    merge_into,
    project_file,
    resource_text,
    set_nested,
    write_atomic,
)
from codeseam.semantics import SemanticMode, semantic_mode_from_config


@dataclass(frozen=True)
class Config:
    repo_root: Path
    data: Json
    config_hash: str
    sources: tuple[str, ...]

    def path(self, section: str, key: str) -> Path:
        value = Path(str(_section(self.data, section).get(key, "")))
        if value.is_absolute():
            return value
        return self.repo_root / value

    def cache_path(self) -> Path:
        cache = self.data.get("cache", {})
        if isinstance(cache, dict) and "path" in cache:
            value = Path(str(cache["path"]))
            return value if value.is_absolute() else self.repo_root / value
        return self.path("output", "root") / "cache"

    @property
    def cache_enabled(self) -> bool:
        return self._cache_flag("enabled")

    def cache_stage_enabled(self, key: str) -> bool:
        del key
        return self.cache_enabled

    def relation_policy_enabled(self, key: str) -> bool:
        return bool(_section(self.data, "relations").get(key, False))

    @property
    def semantic_mode(self) -> SemanticMode:
        return semantic_mode_from_config(self.data)

    def _cache_flag(self, key: str) -> bool:
        return bool(_section(self.data, "cache").get(key, True))


def load_config(
    repo_root: Path | None = None,
    cli_overrides: Json | None = None,
) -> Config:
    root = (repo_root or Path.cwd()).resolve()
    merged = default_config()
    sources: list[str] = ["defaults"]

    for path in config_candidates(root):
        if path.exists():
            merge_into(merged, _read_toml(path))
            sources.append(str(path.relative_to(root)))

    ignore_patterns = _read_codeseamignore(project_file(root, "ignore"))
    if ignore_patterns:
        selection = _section(merged, "selection")
        exclude = selection.get("exclude", [])
        selection["exclude"] = [
            *(exclude if isinstance(exclude, list) else []),
            *ignore_patterns,
        ]
        sources.append(".codeseamignore")

    env_config = _env_config(os.environ)
    if env_config:
        merge_into(merged, env_config)
        sources.append("environment")

    if cli_overrides:
        cleaned = _clean_overrides(cli_overrides)
        if cleaned:
            merge_into(merged, cleaned)
            sources.append("cli")

    project = _section(merged, "project")
    repo_value = str(project.get("repo_root", "auto"))
    if repo_value != "auto":
        root = (
            (root / repo_value).resolve()
            if not Path(repo_value).is_absolute()
            else Path(repo_value)
        )
        project["repo_root"] = str(root)

    return Config(
        repo_root=root,
        data=merged,
        config_hash=_config_hash(merged),
        sources=tuple(sources),
    )


def materialize_init_config(path: Path) -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(path, resource_text(INIT_CONFIG_RESOURCE))
    return True


def _read_toml(path: Path) -> Json:
    try:
        with path.open("rb") as file:
            data = tomllib.load(file)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Invalid TOML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"Config file must contain a TOML table: {path}")
    return cast(Json, data)


def _section(config: Json, key: str) -> Json:
    value = config.get(key)
    if isinstance(value, dict):
        return cast(Json, value)
    section: Json = {}
    config[key] = section
    return section


def _read_codeseamignore(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [
        line
        for raw_line in path.read_text(encoding="utf-8").splitlines()
        if (line := raw_line.strip()) and not line.startswith("#")
    ]


def _env_config(environ: os._Environ[str]) -> Json:
    config: Json = {}
    mapping = {
        "CODESEAM_REPO_ROOT": ("project", "repo_root"),
        "CODESEAM_OUTPUT_ROOT": ("output", "root"),
        "CODESEAM_CACHE_ENABLED": ("cache", "enabled"),
        "CODESEAM_CACHE_PATH": ("cache", "path"),
        "CODESEAM_TOOL_TIMEOUT_SECONDS": ("tools", "timeout_seconds"),
    }
    for env_name, path in mapping.items():
        if env_name in environ:
            set_nested(config, path, _coerce_env_value(environ[env_name]))
    return config


def _clean_overrides(overrides: Json) -> Json:
    cleaned: Json = {}
    for dotted_key, value in overrides.items():
        if value is None:
            continue
        set_nested(cleaned, tuple(dotted_key.split(".")), value)
    return cleaned


def _coerce_env_value(value: str) -> bool | int | str:
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if value.isdigit():
        return int(value)
    return value


def _config_hash(config: Json) -> str:
    payload = dumps_jsonable_stable(config)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
