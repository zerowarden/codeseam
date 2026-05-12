from __future__ import annotations

from codeseam.platform import dumps_jsonable_stable


def md_text(value: object) -> str:
    text = str(value).replace("\r\n", "\n").replace("\r", "\n").strip()
    return " ".join(part.strip() for part in text.split("\n") if part.strip())


def md_code(value: object) -> str:
    text = md_text(value)
    if "`" not in text:
        return f"`{text}`"
    fence = "`" * (max(part.count("`") for part in text.split("`")) + 1)
    return f"{fence} {text} {fence}"


def md_json(value: object) -> str:
    return dumps_jsonable_stable(value)


def label(value: object) -> str:
    return str(value).replace("_", " ").capitalize()
