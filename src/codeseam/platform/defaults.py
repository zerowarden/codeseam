from __future__ import annotations

import tomllib
from copy import deepcopy
from importlib import resources

from codeseam.platform.json import Json
from codeseam.platform.paths import DEFAULT_CACHE_ROOT, DEFAULT_OUTPUT_ROOT

DEFAULT_CONFIG_RESOURCE = "default_codeseam.toml"
INIT_CONFIG_RESOURCE = "init_codeseam.toml"
CODESEAMIGNORE_RESOURCE = "default_codeseamignore"


def resource_text(name: str) -> str:
    return resources.files("codeseam.resources").joinpath(name).read_text()


def default_config() -> Json:
    config = deepcopy(tomllib.loads(resource_text(DEFAULT_CONFIG_RESOURCE)))
    config.setdefault("output", {})["root"] = DEFAULT_OUTPUT_ROOT.as_posix()
    config.setdefault("cache", {})["path"] = DEFAULT_CACHE_ROOT.as_posix()
    return config
