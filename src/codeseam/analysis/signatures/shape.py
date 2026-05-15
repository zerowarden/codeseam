from __future__ import annotations

import re
from collections.abc import Sequence

from codeseam.platform import sha256_text

GENERIC_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")


def canonical_shape(
    params: Sequence[str],
    return_type: str,
    declared_generics: Sequence[str] | None = None,
) -> tuple[str, str]:
    mapping: dict[str, str] = {}
    declared = set(declared_generics or [])

    def normalize(value: str) -> str:
        return GENERIC_RE.sub(lambda match: _replace(match.group(0), mapping, declared), value)

    shape = f"fn({','.join(normalize(param) for param in params)})->{normalize(return_type)}"
    return shape, sha256_text(shape)


def _replace(token: str, mapping: dict[str, str], declared: set[str]) -> str:
    if token not in declared and not (len(token) == 1 and token.isupper()):
        return token
    if token not in mapping:
        mapping[token] = f"G{len(mapping)}"
    return mapping[token]
