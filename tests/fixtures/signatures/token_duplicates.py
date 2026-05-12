from __future__ import annotations


def relation_callsite_payload(pattern: CallsitePattern) -> Json:
    payload = {
        "kind": pattern.kind,
        "symbol": pattern.symbol,
        "file": pattern.file,
        "line": pattern.line,
        "receiver": pattern.receiver,
        "argument_count": pattern.argument_count,
    }
    if pattern.receiver:
        payload["receiver"] = pattern.receiver
    if pattern.argument_count:
        payload["argument_count"] = pattern.argument_count
    return payload


def signature_callsite_payload(pattern: CallsitePattern) -> Json:
    payload = {
        "kind": pattern.kind,
        "symbol": pattern.symbol,
        "file": pattern.file,
        "line": pattern.line,
        "receiver": pattern.receiver,
        "argument_count": pattern.argument_count,
    }
    if pattern.receiver:
        payload["receiver"] = pattern.receiver
    if pattern.argument_count:
        payload["argument_count"] = pattern.argument_count
    return payload
