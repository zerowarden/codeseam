from __future__ import annotations

from collections.abc import Mapping

from codeseam.platform.errors import ConfigError
from codeseam.semantics.enrichment import SemanticMode

SEMANTICS_SECTION = "semantics"
SEMANTIC_MODE_KEY = "mode"


def semantic_mode_from_config(config: Mapping[str, object]) -> SemanticMode:
    section = config.get(SEMANTICS_SECTION)
    value = section.get(SEMANTIC_MODE_KEY) if isinstance(section, Mapping) else None
    if value is None:
        return SemanticMode.OFF
    try:
        return SemanticMode(value)
    except ValueError as exc:
        allowed = ", ".join(mode.value for mode in SemanticMode)
        raise ConfigError(f"semantics.mode must be one of {allowed}: {value!r}") from exc


__all__ = ["SEMANTICS_SECTION", "SEMANTIC_MODE_KEY", "semantic_mode_from_config"]
