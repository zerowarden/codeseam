def aggregate_latencies(samples):
    overall = 0
    peak = None
    for sample in samples:
        overall += sample
        if peak is None or sample > peak:
            peak = sample
    mean = overall / len(samples) if samples else 0
    return {"total": overall, "highest": peak, "average": mean}
