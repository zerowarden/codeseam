from __future__ import annotations

import re
from functools import lru_cache

WORD_RE = re.compile(r"[A-Za-z0-9]+")


def text(value: object, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def text_list(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return [item for value in values if (item := text(value))]


def string_tuple(values: object, *, coerce: bool = False) -> tuple[str, ...]:
    if not isinstance(values, list | tuple):
        return ()
    if coerce:
        return tuple(str(item) for item in values)
    return tuple(item for item in values if isinstance(item, str))


def single_line(value: object) -> str:
    return " ".join(str(value or "").split())


def plural_suffix(count: int) -> str:
    return "" if count == 1 else "s"


def plural_noun(count: int, singular: str, plural: str | None = None) -> str:
    return singular if count == 1 else plural or f"{singular}s"


def _identifier_tokens(value: str) -> list[str]:
    spaced = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", value)
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", spaced)
    return [token.lower() for token in WORD_RE.findall(spaced.replace("_", " "))]


@lru_cache(maxsize=32768)
def cached_identifier_tokens(value: str) -> tuple[str, ...]:
    return tuple(_identifier_tokens(value))


def identifier_tokens(value: str) -> list[str]:
    return list(cached_identifier_tokens(value))


def normalize_identifier(value: str) -> str:
    return " ".join(cached_identifier_tokens(value))


def is_public_identifier(value: object) -> bool:
    name = text(value)
    return bool(name and not name.startswith("_"))


@lru_cache(maxsize=4096)
def levenshtein_distance(left: str, right: str) -> int:
    if left == right:
        return 0
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for index, char in enumerate(left, 1):
        current = [index]
        for other_index, other in enumerate(right, 1):
            current.append(
                min(
                    previous[other_index] + 1,
                    current[other_index - 1] + 1,
                    previous[other_index - 1] + (char != other),
                )
            )
        previous = current
    return previous[-1]


@lru_cache(maxsize=4096)
def similarity_ratio(left: str, right: str) -> float:
    if left == right:
        return 1.0
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    distance = levenshtein_distance(left, right)
    return round(1 - distance / max(len(left), len(right)), 4)
