import logging

log = logging.getLogger(__name__)


def run_cleanup(job, store):
    log.info("starting %s", job.name)
    removed = store.delete_older_than(job.days)
    log.info("removed %d rows", removed)
    return removed


def run_vacuum(job, store):
    log.info("starting %s", job.name)
    store.vacuum()
    return store.size()
