from __future__ import annotations

import pytest


def skip_without_typescript(result: object) -> None:
    if "typescript_package_unavailable" in getattr(result, "caveats", ()):
        pytest.skip("TypeScript package is not resolvable by Node")
