from __future__ import annotations

from codeseam.adapters.languages.manifests import ManifestMatcher

PYTHON_MANIFEST_MATCHERS: tuple[ManifestMatcher, ...] = (
    ManifestMatcher("python", ("pyproject.toml", "setup.cfg", "requirements*.txt")),
    ManifestMatcher("test", ("pytest.ini",)),
    ManifestMatcher("uv", ("uv.lock",)),
)

__all__ = ["PYTHON_MANIFEST_MATCHERS"]
