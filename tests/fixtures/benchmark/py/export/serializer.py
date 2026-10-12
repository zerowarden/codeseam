import json


def write_json(path, payload):
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def normalize_records(records):
    cleaned = []
    for record in records:
        name = record.get("name", "").strip().lower()
        if not name:
            continue
        amount = float(record.get("amount", 0))
        cleaned.append({"name": name, "amount": round(amount, 2)})
    cleaned.sort(key=lambda item: item["name"])
    return cleaned
