"""Equivalent Python and TypeScript functions produce the same language-neutral features.

Thresholds and heuristics are shared, so the adapters must agree on the
vocabulary they feed them (`analysis/signatures/vocabulary.py`).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from helpers import extract_source

from codeseam.analysis import FunctionRecord, SignatureRecord

PAIRS = {
    "guard-loop-update": (
        "def total(items, limit=10):\n"
        "    if not items:\n"
        "        return 0\n"
        "    result = 0\n"
        "    for item in items:\n"
        "        result += item\n"
        "    return result\n",
        "function total(items, limit = 10) {\n"
        "  if (!items) {\n"
        "    return 0;\n"
        "  }\n"
        "  let result = 0;\n"
        "  for (const item of items) {\n"
        "    result += item;\n"
        "  }\n"
        "  return result;\n"
        "}\n",
    ),
    "try-catch-await": (
        "async def load(client, key):\n"
        "    try:\n"
        "        data = await client.fetch(key)\n"
        "    except KeyError as error:\n"
        "        raise error\n"
        "    await client.close()\n"
        "    return data\n",
        "async function load(client, key) {\n"
        "  try {\n"
        "    const data = await client.fetch(key);\n"
        "  } catch (error) {\n"
        "    throw error;\n"
        "  }\n"
        "  await client.close();\n"
        "  return data;\n"
        "}\n",
    ),
    "named-lambda": (
        "scale = lambda value, factor=2: value * factor\n",
        "const scale = (value, factor = 2) => value * factor;\n",
    ),
    "variadic": (
        "def combine(*scores):\n    return sum(scores)\n",
        "function combine(...scores) {\n  return sum(scores);\n}\n",
    ),
}


def _extract(tmp_path: Path, language: str, source: str) -> tuple[SignatureRecord, FunctionRecord]:
    analysis = extract_source(tmp_path / language, language, source)
    (signature,) = analysis.signatures
    (function,) = analysis.functions
    return signature, function


def _features(signature: SignatureRecord, function: FunctionRecord) -> dict[str, object]:
    return {
        "statements": signature.statement_sequence,
        "controls": signature.control_context_vector,
        "defaults": signature.parameter_default_roles,
        "parameters": len(signature.parameters),
        "graph": signature.graph_features,
        "type_source": signature.type_source,
        "caveats": signature.caveats,
        "metrics": (
            function.branch_count,
            function.loop_count,
            function.return_count,
            function.max_nesting,
        ),
    }


@pytest.mark.parametrize(("python", "typescript"), PAIRS.values(), ids=PAIRS.keys())
def test_equivalent_functions_have_equal_features(
    tmp_path: Path, python: str, typescript: str
) -> None:
    python_features = _features(*_extract(tmp_path, "Python", python))
    typescript_features = _features(*_extract(tmp_path, "TypeScript", typescript))

    assert python_features == typescript_features


def test_variadic_parameters_stay_in_the_python_shape(tmp_path: Path) -> None:
    signature, _ = _extract(tmp_path, "Python", "def combine(*scores: float) -> float:\n    ...\n")

    assert signature.canonical_shape == "fn(list[float])->float"
