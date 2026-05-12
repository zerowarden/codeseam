def _duplicate_overlaps(members: list[dict], duplicates: list[dict]) -> list[str]:
    ids: set[str] = set()
    for duplicate in duplicates:
        ranges = [duplicate.get("first", {}), duplicate.get("second", {})]
        if any(ranges_overlap(member, location) for member in members for location in ranges):
            ids.add(str(duplicate["duplicate_id"]))
    return sorted(ids)


def _finding_overlaps(members: list[dict], findings: list[dict]) -> list[str]:
    ids: set[str] = set()
    for finding in findings:
        if str(finding.get("category")) != "structure":
            continue
        if any(ranges_overlap(member, finding) for member in members):
            ids.add(str(finding["finding_id"]))
    return sorted(ids)
