import csv


def read_csv_rows(path):
    with open(path, newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader)


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
