def report_single_line(value: object) -> str:
    return " ".join(str(value or "").split())
