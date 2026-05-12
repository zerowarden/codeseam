from __future__ import annotations

import sqlite3
from pathlib import Path

from codeseam.cache.blobs import load_cache_blob
from codeseam.cache.store import connect_cache_db
from codeseam.platform import Json
from codeseam.version import CACHE_DB, CACHE_STATS_SCHEMA_VERSION


def cache_stats(root: Path) -> Json:
    db_path = root / CACHE_DB
    if not db_path.exists():
        return {
            "schema_version": CACHE_STATS_SCHEMA_VERSION,
            "cache_root": str(root),
            "database": str(db_path),
            "exists": False,
            "entry_count": 0,
            "namespaces": {},
            "relation_pair_results": {},
        }
    connection = connect_cache_db(db_path)
    try:
        namespace_rows = connection.execute(
            """
            select namespace, count(*)
            from cache_entries
            group by namespace
            order by namespace
            """
        ).fetchall()
        namespaces = {str(namespace): int(count) for namespace, count in namespace_rows}
        return {
            "schema_version": CACHE_STATS_SCHEMA_VERSION,
            "cache_root": str(root),
            "database": str(db_path),
            "exists": True,
            "entry_count": sum(namespaces.values()),
            "namespaces": namespaces,
            "relation_pair_results": _relation_pair_result_counts(connection),
            "size_bytes": db_path.stat().st_size,
        }
    finally:
        connection.close()


def _relation_pair_result_counts(connection: sqlite3.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    rows = connection.execute(
        "select payload from cache_entries where namespace = ?",
        ("relation_pairs",),
    ).fetchall()
    for (payload,) in rows:
        result = _cache_result(payload)
        counts[result] = counts.get(result, 0) + 1
    return counts


def _cache_result(payload: object) -> str:
    if not isinstance(payload, bytes):
        return "invalid"
    try:
        data = load_cache_blob(payload)
    except Exception:
        return "invalid"
    return str(data.get("result", "unknown")) if isinstance(data, dict) else "unknown"
