from __future__ import annotations

from functools import cache

from jinja2 import Environment, PackageLoader, StrictUndefined

from codeseam.output.reports.markdown_filters import label, md_code, md_json, md_text
from codeseam.platform import Json


def render_template(name: str, context: Json) -> str:
    return _environment().get_template(name).render(**context).rstrip() + "\n"


@cache
def _environment() -> Environment:
    environment = Environment(
        loader=PackageLoader("codeseam.output.reports", "templates"),
        autoescape=False,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    environment.filters.update(
        {
            "label": label,
            "md_code": md_code,
            "md_json": md_json,
            "md_text": md_text,
        }
    )
    return environment
