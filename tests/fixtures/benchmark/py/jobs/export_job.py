import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)


def run_export(job, store):
    target = Path(job.path)
    if not target.exists():
        raise FileNotFoundError(target)
    settings = json.loads(job.settings or "{}")
    batch_size = int(settings.get("batch_size", 500))
    if batch_size <= 0:
        raise ValueError(f"batch size must be positive: {batch_size}")
    log.info("starting %s with batch size %d", job.name, batch_size)
    written = 0
    with target.open("w") as handle:
        for page in store.pages(batch_size):
            handle.write("\n".join(",".join(map(str, row)) for row in page))
            written += len(page)
    log.info("exported %d rows", written)
    return written
