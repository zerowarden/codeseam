from __future__ import annotations

from codeseam.adapters.languages.ecmascript.compiler_facts import TYPESCRIPT_CONFIG_MANIFEST
from codeseam.adapters.languages.manifests import ManifestMatcher

ECMASCRIPT_MANIFEST_MATCHERS: tuple[ManifestMatcher, ...] = (
    ManifestMatcher(
        TYPESCRIPT_CONFIG_MANIFEST,
        ("tsconfig.json", "tsconfig.*.json"),
    ),
    ManifestMatcher(
        "node",
        ("package.json", "pnpm-lock.yaml", "yarn.lock", "package-lock.json"),
    ),
)

__all__ = ["ECMASCRIPT_MANIFEST_MATCHERS"]
