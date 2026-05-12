def completed_result(raw, stderr):
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return failure(
            status="failed",
            reason="semantic_worker_bad_response",
            stderr=stderr,
            code=1,
        )

    if not isinstance(payload, dict):
        return failure(
            status="failed",
            reason="semantic_worker_bad_response",
            stderr=stderr,
            code=1,
        )

    return payload
