from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from codeseam.config import Config
from codeseam.output.serializers.review import review_tier as explain_review_tier
from codeseam.platform import (
    ConfigError,
    Json,
    OutputPaths,
    as_json_objects,
    dumps_jsonable_stable,
    json_int,
    load_jsonl_objects,
    text,
    text_list,
)


@dataclass(frozen=True)
class ExplainRenderOptions:
    json_output: bool
    full: bool
    source: bool
    evidence: bool
    pairs: bool
    top: int


def load_explain(config: Config, target_id: str) -> Json | None:
    paths = OutputPaths(config.path("output", "root"))
    sidecars = (paths.artifact("agent_analysis"), paths.artifact("agent_observations"))
    if not any(path.exists() for path in sidecars):
        raise ConfigError(f"Explain sidecars not found: {paths.directory('agent')}")
    for path in sidecars:
        for item in load_jsonl_objects(path, missing_ok=True):
            if item.get("target_id") == target_id:
                return item
    return None


def render_explain(
    item: Json,
    options: ExplainRenderOptions,
    *,
    source_lines: list[str] | None = None,
) -> str:
    if options.json_output or options.full:
        payload = item if options.full else _compact_payload(item)
        return dumps_jsonable_stable(payload, pretty=True) + "\n"

    lines = _compact_lines(item)
    if options.source:
        lines.extend(["", *(source_lines or ["Source:", "  <source unavailable>"])])
    if options.evidence:
        lines.extend(["", *_evidence_lines(item, options.top)])
    if options.pairs:
        lines.extend(["", *_pair_lines(item, options.top)])
    return "\n".join(lines).rstrip() + "\n"


def explain_source_lines(item: Json, repo_root: Path, top: int) -> list[str]:
    lines = ["Source:"]
    for member in _explain_member_refs(item)[: max(1, top)]:
        path = text(member.get("file"))
        start = json_int(member.get("start_line"), 1)
        end = json_int(member.get("end_line"), start)
        symbol = text(member.get("symbol"))
        lines.append(f"-- {path}:{start}-{end} {symbol}".rstrip())
        lines.extend(_snippet(repo_root / path, start, end))
    return lines


def _compact_payload(item: Json) -> Json:
    return {
        "target_id": text(item.get("target_id")),
        "review_tier": explain_review_tier(item),
        "action_status": _action_status(item),
        "primary_action": _primary_action(item),
        "confidence": _confidence(item),
        "refactor_safety": text(item.get("refactor_safety")),
        "shape": _shape(item),
        "relation": _relation(item),
        "files": _files(item),
        "symbols": _symbols(item),
        "action": _action(item),
        "guard": _guard(item),
        "semantic_guardrails": _semantic_guardrails(item),
        "adapter_capabilities": _adapter_capabilities(item),
    }


def _compact_lines(item: Json) -> list[str]:
    lines = [
        (
            f"{text(item.get('target_id'))} {explain_review_tier(item)} "
            f"{_action_status(item)} "
            f"conf={_short_float(_confidence(item))} "
            f"safety={text(item.get('refactor_safety'))}"
        ).strip(),
        f"{_shape(item)} | {_relation(item)}",
        ", ".join(_files(item)),
        "symbols: " + ", ".join(_symbols(item)),
        f"action: {_action(item)}",
        f"guard: {_guard(item)}",
    ]
    if guardrails := _semantic_guardrail_lines(item):
        lines.extend(["", *guardrails])
    if capabilities := _adapter_capability_lines(item):
        lines.extend(["", *capabilities])
    lines.append("more: --source | --evidence | --pairs --top 3 | --json --full")
    return lines


def _evidence_lines(item: Json, top: int) -> list[str]:
    lines = ["Evidence:"]
    lines.append(f"- strength: {text(item.get('evidence_strength'))}")
    if classes := text_list(item.get("evidence_classes")):
        lines.append("- classes: " + ", ".join(classes[: max(1, top)]))
    if kinds := text_list(item.get("evidence_kinds")):
        lines.append("- kinds: " + ", ".join(kinds[: max(1, top)]))
    for reason in text_list(item.get("reasons"))[: max(1, top)]:
        lines.append(f"- reason: {reason}")
    return lines


def _action_status(item: Json) -> str:
    return text(item.get("action_status")) or "observe"


def _primary_action(item: Json) -> str:
    return text(item.get("primary_action")) or _action(item)


def _pair_lines(item: Json, top: int) -> list[str]:
    pairs = _relation_pairs(item)[: max(1, top)]
    if not pairs:
        return ["Pairs:", "- none"]
    lines = ["Pairs:"]
    for pair in pairs:
        left = _member_label(pair.get("left"))
        right = _member_label(pair.get("right"))
        relation = text(pair.get("relation_kind"))
        relatedness = _short_float(_metric_float(pair, "relatedness_score"))
        refactorability = _short_float(_metric_float(pair, "refactorability_score"))
        risk = _short_float(_metric_float(pair, "risk_score"))
        deltas = ", ".join(text_list(pair.get("delta_kinds"))) or "none"
        lines.append(
            f"- {left} <-> {right}: {relation}; "
            f"rel={relatedness}; refactor={refactorability}; risk={risk}; deltas={deltas}"
        )
    return lines


def _shape(item: Json) -> str:
    title = text(item.get("title"))
    return title.removeprefix("Shared signature shape ").strip() or title


def _relation(item: Json) -> str:
    metrics = item.get("metrics")
    if isinstance(metrics, dict):
        counts = metrics.get("relation_kind_counts")
        if isinstance(counts, dict) and counts:
            return text(next(iter(counts)))
    pairs = _relation_pairs(item)
    if pairs:
        return text(pairs[0].get("relation_kind"))
    return "unknown_relation"


def _files(item: Json) -> list[str]:
    values = text_list(item.get("files"))
    if values:
        return values
    return list(dict.fromkeys(text(member.get("file")) for member in _explain_member_refs(item)))


def _symbols(item: Json) -> list[str]:
    return [
        symbol
        for symbol in dict.fromkeys(
            text(member.get("symbol")) for member in _explain_member_refs(item)
        )
        if symbol
    ]


def _action(item: Json) -> str:
    action = text(item.get("primary_action"))
    if action:
        return action
    summary = item.get("refactor_action_summary")
    if isinstance(summary, dict):
        action = text(summary.get("primary_action"))
        if action:
            return action
    return "observe"


def _guard(item: Json) -> str:
    claims = text_list(item.get("non_claims"))
    if claims:
        return claims[0].replace("Signature-shape equality", "same signature shape")
    return "same signature shape != same behavior"


def _semantic_guardrails(item: Json) -> Json:
    value = item.get("semantic_guardrails")
    return value if isinstance(value, dict) else {}


def _adapter_capabilities(item: Json) -> list[Json]:
    return as_json_objects(item.get("adapter_capabilities"))


def _adapter_capability_lines(item: Json) -> list[str]:
    capabilities = _adapter_capabilities(item)
    if not capabilities:
        return []
    lines = ["Adapter capability facts:"]
    for capability in capabilities[:3]:
        language = text(capability.get("language"))
        syntax = text(capability.get("syntax_frontend")) or "unknown"
        relation_detail = _bool_label(capability.get("relation_detail"))
        compiler_semantics = _bool_label(capability.get("compiler_semantics"))
        lines.append(
            f"- {language}: syntax={syntax}; "
            f"relation_detail={relation_detail}; "
            f"compiler_semantics={compiler_semantics}"
        )
    if any(capability.get("compiler_semantics") is not True for capability in capabilities):
        lines.append("- compiler semantics unavailable; relation evidence is syntax-level")
    return lines


def _semantic_guardrail_lines(item: Json) -> list[str]:
    guardrails = _semantic_guardrails(item)
    roles = text_list(guardrails.get("roles"))
    reasons = text_list(guardrails.get("reasons")) or [
        reason
        for reason in text_list(item.get("downgrade_reasons"))
        if reason.startswith("Semantic role cap:")
    ]
    if not roles and not reasons:
        return []
    lines = ["Semantic role guardrails:"]
    if roles:
        lines.append("- roles: " + ", ".join(roles))
    for reason in reasons[:3]:
        lines.append(f"- {reason}")
    return lines


def _explain_items(item: Json, key: str) -> list[Json]:
    return as_json_objects(item.get(key))


def _explain_member_refs(item: Json) -> list[Json]:
    refs = [*as_json_objects(item.get("locations"))]
    for pair in _relation_pairs(item):
        refs.extend(
            pair_item
            for pair_item in (pair.get("left"), pair.get("right"))
            if isinstance(pair_item, dict)
        )
    deduped: dict[tuple[str, str, str], Json] = {}
    for ref in refs:
        key = (
            text(ref.get("file")),
            text(ref.get("start_line")),
            text(ref.get("symbol")),
        )
        if key[0]:
            deduped.setdefault(key, ref)
    return list(deduped.values())


def _relation_pairs(item: Json) -> list[Json]:
    return sorted(
        _explain_items(item, "structural_relation_pairs"),
        key=lambda pair: (
            _metric_float(pair, "pair_confidence") or _metric_float(pair, "relatedness_score")
        ),
        reverse=True,
    )


def _member_label(value: object) -> str:
    if not isinstance(value, dict):
        return "unknown"
    path = text(value.get("file"))
    line = text(value.get("start_line"))
    symbol = text(value.get("symbol"))
    return f"{path}:{line} {symbol}".strip()


def _snippet(path: Path, start: int, end: int) -> list[str]:
    if not path.exists() or not path.is_file():
        return ["  <source unavailable>"]
    source = path.read_text(encoding="utf-8", errors="replace").splitlines()
    start_index = max(0, start - 1)
    end_index = min(len(source), max(start, end))
    return [f"  {line}" for line in source[start_index:end_index]] or ["  <empty snippet>"]


def _confidence(item: Json) -> float:
    return _metric_float(item, "recommendation_confidence") or _metric_float(
        item,
        "confidence",
    )


def _metric_float(metrics: Json, key: str) -> float:
    value = metrics.get(key)
    return float(value) if isinstance(value, int | float) else 0.0


def _short_float(value: float) -> str:
    rendered = f"{value:.3f}".rstrip("0").rstrip(".")
    return rendered.replace("0.", ".") if rendered.startswith("0.") else rendered


def _bool_label(value: object) -> str:
    return "yes" if value is True else "no"


__all__ = ["ExplainRenderOptions", "explain_source_lines", "load_explain", "render_explain"]
