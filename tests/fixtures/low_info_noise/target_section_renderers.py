from __future__ import annotations


def _evidence_lines(target: Json, top: int) -> list[str]:
    lines = ["Evidence:"]
    lines.append(f"- strength: {text(target.get('evidence_strength'))}")
    if classes := text_list(target.get("evidence_classes")):
        lines.append("- classes: " + ", ".join(classes[:max(1, top)]))
    if kinds := text_list(target.get("evidence_kinds")):
        lines.append("- kinds: " + ", ".join(kinds[:max(1, top)]))
    for reason in text_list(target.get("reasons"))[:max(1, top)]:
        lines.append(f"- reason: {reason}")
    return lines


def _pair_lines(target: Json, top: int) -> list[str]:
    pairs = _relation_pairs(target)[:max(1, top)]
    if not pairs:
        return ["Pairs:", "- none"]
    lines = ["Pairs:"]
    for pair in pairs:
        left = _member_label(pair.get("left"))
        right = _member_label(pair.get("right"))
        relation = text(pair.get("relation_kind"))
        relatedness = _short_float(metric_float(pair, "relatedness_score"))
        refactorability = _short_float(metric_float(pair, "refactorability_score"))
        risk = _short_float(metric_float(pair, "risk_score"))
        deltas = ", ".join(text_list(pair.get("delta_kinds"))) or "none"
        lines.append(
            f"- {left} <-> {right}: {relation}; "
            f"rel={relatedness}; refactor={refactorability}; risk={risk}; deltas={deltas}"
        )
    return lines
