from __future__ import annotations

import sqlite3
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

from codeseam.cache.blobs import load_cache_blob
from codeseam.platform import Json
from codeseam.version import (
    CACHE_BUSY_TIMEOUT_MS,
    CACHE_DB,
    CACHE_RUN_STATS_SCHEMA_VERSION,
    CACHE_TIMEOUT_SECONDS,
)

SQLITE_CACHE_SIZE_KIB = 65_536
SQLITE_MMAP_SIZE_BYTES = 268_435_456
SQLITE_MAX_VARIABLES = 900


class PersistentCache:
    def __init__(self, root: Path, *, enabled: bool = True) -> None:
        self.root = root
        self.enabled = enabled
        self._connection: sqlite3.Connection | None = None
        self._dirty = False
        self._gets: dict[str, int] = {}
        self._hits: dict[str, int] = {}
        self._misses: dict[str, int] = {}
        self._sets: dict[str, int] = {}
        self._blob_load_counts: dict[str, int] = {}
        self._blob_load_bytes: dict[str, int] = {}
        self._blob_load_seconds: dict[str, float] = {}
        self._blob_load_max_seconds: dict[str, float] = {}
        self._blob_objects: dict[tuple[str, str], object] = {}

    def get_blob(self, namespace: str, key: str) -> bytes | None:
        if not self.enabled:
            return None
        self._increment(self._gets, namespace)
        row = (
            self._connect()
            .execute(
                "select payload from cache_entries where namespace = ? and key = ?",
                (namespace, key),
            )
            .fetchone()
        )
        self._increment(self._hits if row else self._misses, namespace)
        payload = row[0] if row else None
        return payload if isinstance(payload, bytes) else None

    def get_blob_object(self, namespace: str, key: str) -> object | None:
        if not self.enabled:
            return None
        memo_key = (namespace, key)
        if memo_key in self._blob_objects:
            self._increment(self._gets, namespace)
            self._increment(self._hits, namespace)
            return self._blob_objects[memo_key]
        payload = self.get_blob(namespace, key)
        if not isinstance(payload, bytes):
            return None
        try:
            value = self._load_blob_object(namespace, payload)
        except Exception:
            return None
        self._blob_objects[memo_key] = value
        return value

    def get_blobs(self, namespace: str, keys: Sequence[str]) -> dict[str, bytes]:
        if not self.enabled or not keys:
            return {}
        unique_keys = list(dict.fromkeys(keys))
        self._increment(self._gets, namespace, len(unique_keys))
        found: dict[str, bytes] = {}
        connection = self._connect()
        for chunk in _chunks(unique_keys, SQLITE_MAX_VARIABLES - 1):
            placeholders = ",".join("?" for _ in chunk)
            rows = connection.execute(
                f"""
                select key, payload
                from cache_entries
                where namespace = ? and key in ({placeholders})
                """,
                (namespace, *chunk),
            ).fetchall()
            for key, payload in rows:
                if isinstance(payload, bytes):
                    found[str(key)] = payload
        self._increment(self._hits, namespace, len(found))
        self._increment(self._misses, namespace, len(unique_keys) - len(found))
        return found

    def set_blob(self, namespace: str, key: str, payload: bytes) -> None:
        if not self.enabled:
            return
        self._increment(self._sets, namespace)
        self._connect().execute(
            """
            insert into cache_entries(namespace, key, payload, updated_at)
            values (?, ?, ?, current_timestamp)
            on conflict(namespace, key) do update set
                payload = excluded.payload,
                updated_at = excluded.updated_at
            """,
            (namespace, key, sqlite3.Binary(payload)),
        )
        self._dirty = True
        self._blob_objects.pop((namespace, key), None)

    def set_blobs(self, namespace: str, payloads: Mapping[str, bytes]) -> None:
        if not self.enabled or not payloads:
            return
        self._increment(self._sets, namespace, len(payloads))
        self._connect().executemany(
            """
            insert into cache_entries(namespace, key, payload, updated_at)
            values (?, ?, ?, current_timestamp)
            on conflict(namespace, key) do update set
                payload = excluded.payload,
                updated_at = excluded.updated_at
            """,
            ((namespace, key, sqlite3.Binary(payload)) for key, payload in payloads.items()),
        )
        self._dirty = True
        for key in payloads:
            self._blob_objects.pop((namespace, key), None)

    def close(self) -> None:
        if self._connection is not None:
            if self._dirty:
                self._connection.commit()
            self._connection.close()
            self._connection = None
            self._dirty = False
            self._blob_objects.clear()

    def run_stats(self) -> Json:
        namespaces = sorted(
            {
                *self._gets,
                *self._hits,
                *self._misses,
                *self._sets,
            }
        )
        hits = sum(self._hits.values())
        gets = sum(self._gets.values())
        misses = sum(self._misses.values())
        sets = sum(self._sets.values())
        return {
            "schema_version": CACHE_RUN_STATS_SCHEMA_VERSION,
            "enabled": self.enabled,
            "gets": gets,
            "hits": hits,
            "misses": misses,
            "sets": sets,
            "hit_rate": round(hits / gets, 4) if gets else None,
            "namespaces": {
                namespace: {
                    "gets": self._gets.get(namespace, 0),
                    "hits": self._hits.get(namespace, 0),
                    "misses": self._misses.get(namespace, 0),
                    "sets": self._sets.get(namespace, 0),
                    **self._blob_load_stats(namespace),
                }
                for namespace in namespaces
            },
        }

    def _connect(self) -> sqlite3.Connection:
        if self._connection is None:
            self.root.mkdir(parents=True, exist_ok=True)
            self._connection = connect_cache_db(self.root / CACHE_DB)
            self._connection.execute(
                """
                create table if not exists cache_entries (
                    namespace text not null,
                    key text not null,
                    payload blob not null,
                    updated_at text not null,
                    primary key(namespace, key)
                )
                """
            )
            self._connection.commit()
            self._dirty = False
        return self._connection

    @staticmethod
    def _increment(counter: dict[str, int], namespace: str, amount: int = 1) -> None:
        counter[namespace] = counter.get(namespace, 0) + amount

    def _load_blob_object(self, namespace: str, payload: bytes) -> object:
        started = time.perf_counter()
        value = load_cache_blob(payload)
        elapsed = time.perf_counter() - started
        self._increment(self._blob_load_counts, namespace)
        self._increment(self._blob_load_bytes, namespace, len(payload))
        self._blob_load_seconds[namespace] = self._blob_load_seconds.get(namespace, 0.0) + elapsed
        self._blob_load_max_seconds[namespace] = max(
            self._blob_load_max_seconds.get(namespace, 0.0),
            elapsed,
        )
        return value

    def _blob_load_stats(self, namespace: str) -> Json:
        count = self._blob_load_counts.get(namespace, 0)
        if not count:
            return {}
        total_seconds = self._blob_load_seconds.get(namespace, 0.0)
        return {
            "blob_load_count": count,
            "blob_load_bytes": self._blob_load_bytes.get(namespace, 0),
            "blob_load_ms": round(total_seconds * 1000, 3),
            "blob_load_avg_ms": round(total_seconds * 1000 / count, 3),
            "blob_load_max_ms": round(
                self._blob_load_max_seconds.get(namespace, 0.0) * 1000,
                3,
            ),
        }


def persistent_cache(root: Path, *, enabled: bool) -> PersistentCache:
    return PersistentCache(root, enabled=enabled)


def connect_cache_db(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=CACHE_TIMEOUT_SECONDS)
    _configure_connection(connection)
    return connection


def _configure_connection(connection: sqlite3.Connection) -> None:
    connection.execute("pragma journal_mode = wal")
    connection.execute("pragma synchronous = normal")
    connection.execute("pragma temp_store = memory")
    connection.execute(f"pragma cache_size = -{SQLITE_CACHE_SIZE_KIB}")
    connection.execute(f"pragma mmap_size = {SQLITE_MMAP_SIZE_BYTES}")
    connection.execute(f"pragma busy_timeout = {CACHE_BUSY_TIMEOUT_MS}")


def _chunks(values: Sequence[str], size: int) -> list[Sequence[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]
