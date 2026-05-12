from __future__ import annotations

from pathlib import Path
from typing import Any

from codeseam.cache import CACHE_DB, cache_blob, cache_key, load_cache_blob, persistent_cache


def test_persistent_cache_round_trips_blob_payload(tmp_path: Path) -> None:
    cache = persistent_cache(_cache_root(tmp_path), enabled=True)
    key = cache_key({"kind": "demo", "content_hash": "sha256:x"})
    payload = (("value", 1),)

    cache.set_blob("analysis", key, cache_blob(payload))
    cache.close()

    reopened = persistent_cache(_cache_root(tmp_path), enabled=True)
    assert reopened.get_blob_object("analysis", key) == payload
    assert reopened.get_blob_object("analysis", cache_key({"missing": True})) is None
    stats = reopened.run_stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 1
    _assert_namespace_stats(stats, "analysis", {"gets": 2, "hits": 1, "misses": 1, "sets": 0})
    _assert_blob_load_stats(stats, "analysis", payload=payload)
    assert (_cache_root(tmp_path) / CACHE_DB).exists()
    reopened.close()


def test_persistent_cache_is_noop_when_disabled(tmp_path: Path) -> None:
    cache = persistent_cache(_cache_root(tmp_path), enabled=False)

    cache.set_blob("analysis", "demo", cache_blob({"value": 1}))

    assert cache.get_blob("analysis", "demo") is None
    assert cache.get_blob_object("analysis", "demo") is None
    assert cache.get_blobs("analysis", ["demo"]) == {}
    assert not (_cache_root(tmp_path) / CACHE_DB).exists()


def test_cache_key_is_stable_for_dict_order() -> None:
    assert cache_key({"a": 1, "b": 2}) == cache_key({"b": 2, "a": 1})


def test_persistent_cache_batches_blob_payloads(tmp_path: Path) -> None:
    cache = persistent_cache(_cache_root(tmp_path), enabled=True)
    cache.set_blob("relations", "left", cache_blob({"result": "no_relation"}))
    cache.set_blob("relations", "right", cache_blob({"result": "relation_pair"}))
    cache.close()

    reopened = persistent_cache(_cache_root(tmp_path), enabled=True)
    payloads = reopened.get_blobs("relations", ["left", "right", "missing"])
    left_payload = payloads["left"]
    right_payload = payloads["right"]

    assert isinstance(left_payload, bytes)
    assert isinstance(right_payload, bytes)
    assert load_cache_blob(left_payload) == {"result": "no_relation"}
    assert load_cache_blob(right_payload) == {"result": "relation_pair"}
    assert set(payloads) == {"left", "right"}
    _assert_namespace_stats(
        reopened.run_stats(),
        "relations",
        {"gets": 3, "hits": 2, "misses": 1, "sets": 0},
    )
    reopened.close()


def test_persistent_cache_batches_blob_writes(tmp_path: Path) -> None:
    cache = persistent_cache(_cache_root(tmp_path), enabled=True)

    cache.set_blobs(
        "relations",
        {
            "left": cache_blob({"result": "no_relation"}),
            "right": cache_blob({"result": "relation_pair"}),
        },
    )
    cache.close()

    reopened = persistent_cache(_cache_root(tmp_path), enabled=True)
    payloads = reopened.get_blobs("relations", ["left", "right"])

    assert load_cache_blob(payloads["left"]) == {"result": "no_relation"}
    assert load_cache_blob(payloads["right"]) == {"result": "relation_pair"}
    _assert_namespace_stats(
        reopened.run_stats(),
        "relations",
        {"gets": 2, "hits": 2, "misses": 0, "sets": 0},
    )
    reopened.close()


def test_persistent_cache_memoizes_blob_objects(tmp_path: Path) -> None:
    cache = persistent_cache(_cache_root(tmp_path), enabled=True)
    payload = {"result": "relation_pairs"}
    cache.set_blob("relations", "group", cache_blob(payload))
    cache.close()

    reopened = persistent_cache(_cache_root(tmp_path), enabled=True)
    first = reopened.get_blob_object("relations", "group")
    second = reopened.get_blob_object("relations", "group")

    assert first == payload
    assert second is first
    stats = reopened.run_stats()
    _assert_namespace_stats(stats, "relations", {"gets": 2, "hits": 2, "misses": 0, "sets": 0})
    _assert_blob_load_stats(stats, "relations", payload=payload)
    reopened.close()


def _cache_root(tmp_path: Path) -> Path:
    return tmp_path / ".cache" / "codeseam"


def _assert_namespace_stats(
    stats: dict[str, Any],
    namespace: str,
    expected: dict[str, int],
) -> None:
    namespace_stats = stats["namespaces"][namespace]
    assert {key: namespace_stats[key] for key in expected} == expected


def _assert_blob_load_stats(
    stats: dict[str, Any],
    namespace: str,
    *,
    payload: object,
) -> None:
    namespace_stats = stats["namespaces"][namespace]
    assert namespace_stats["blob_load_count"] == 1
    assert namespace_stats["blob_load_bytes"] == len(cache_blob(payload))
    assert namespace_stats["blob_load_ms"] >= 0
    assert namespace_stats["blob_load_avg_ms"] >= 0
    assert namespace_stats["blob_load_max_ms"] >= 0
