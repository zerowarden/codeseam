import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)


def run_import(job, store):
    source = Path(job.path)
    if not source.exists():
        raise FileNotFoundError(source)
    settings = json.loads(job.settings or "{}")
    batch_size = int(settings.get("batch_size", 100))
    if batch_size <= 0:
        raise ValueError(f"batch size must be positive: {batch_size}")
    log.info("starting %s with batch size %d", job.name, batch_size)
    rows = []
    for line in source.read_text().splitlines():
        if not line.strip():
            continue
        rows.append(line.split(","))
        if len(rows) >= batch_size:
            store.insert_many(rows)
            rows = []
    if rows:
        store.insert_many(rows)
    return store.count()
