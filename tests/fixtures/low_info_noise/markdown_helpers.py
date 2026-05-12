from __future__ import annotations


def md_text(value: object) -> str:
    text = str(value).replace("\r\n", "\n").replace("\r", "\n").strip()
    return " ".join(part.strip() for part in text.split("\n") if part.strip())


def md_code(value: object) -> str:
    text = md_text(value)
    if "`" not in text:
        return f"`{text}`"
    fence = "`" * (max(part.count("`") for part in text.split("`")) + 1)
    return f"{fence} {text} {fence}"
