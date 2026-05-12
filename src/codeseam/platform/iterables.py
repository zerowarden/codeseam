from __future__ import annotations

from collections.abc import Hashable, Iterable


def dedupe(values: Iterable[Hashable]) -> list[Hashable]:
    return list(dict.fromkeys(values))
