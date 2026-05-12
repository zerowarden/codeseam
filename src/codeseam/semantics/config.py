from __future__ import annotations

from collections.abc import Mapping

from codeseam.semantics.enrichment import SemanticMode, semantic_mode

SEMANTICS_SECTION = "semantics"
SEMANTIC_MODE_KEY = "mode"


def semantic_mode_from_config(config: Mapping[str, object]) -> SemanticMode:
    section = config.get(SEMANTICS_SECTION)
    if not isinstance(section, Mapping):
        return SemanticMode.OFF
    return semantic_mode(section.get(SEMANTIC_MODE_KEY))


__all__ = ["SEMANTICS_SECTION", "SEMANTIC_MODE_KEY", "semantic_mode_from_config"]
