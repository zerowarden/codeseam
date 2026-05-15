from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from helpers import cache_factory, cache_root

from codeseam.cache import (
    CACHE_DB,
    PersistentCache,
    cache_blob,
    cache_key,
    load_cache_blob,
)
from codeseam.platform import Json

__all__ = ["cache_factory", "cache_root"]


def test_persistent_cache_round_trips_blob_payload(
    cache_root: Path,
    cache_factory: Callable[..., PersistentCache],
) -> None:
    cache = cache_factory()
    key = cache_key({"kind": "demo", "content_hash": "sha256:x"})
    payload = (("value", 1),)

    cache.set_blob("analysis", key, cache_blob(payload))
    cache.close()

    reopened = cache_factory()
    assert reopened.get_blob_object("analysis", key) == payload
    assert reopened.get_blob_object("analysis", cache_key({"missing": True})) is None
    assert (cache_root / CACHE_DB).exists()


def test_persistent_cache_run_stats_count_read_hits_and_misses(
    cache_factory: Callable[..., PersistentCache],
) -> None:
    cache = cache_factory()
    key = cache_key({"kind": "demo", "content_hash": "sha256:x"})
    payload = (("value", 1),)
    blob = cache_blob(payload)

    cache.set_blob("analysis", key, blob)
    cache.close()

    reopened = cache_factory()
    assert reopened.get_blob_object("analysis", key) == payload
    assert reopened.get_blob_object("analysis", cache_key({"missing": True})) is None
    stats = reopened.run_stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 1
    _assert_namespace_stats(stats, "analysis", {"gets": 2, "hits": 1, "misses": 1, "sets": 0})
    _assert_blob_load_stats(stats, "analysis", blob_size=len(blob))


def test_persistent_cache_is_noop_when_disabled(
    cache_root: Path,
    cache_factory: Callable[..., PersistentCache],
) -> None:
    cache = cache_factory(enabled=False)

    cache.set_blob("analysis", "demo", cache_blob({"value": 1}))

    assert cache.get_blob("analysis", "demo") is None
    assert cache.get_blob_object("analysis", "demo") is None
    assert cache.get_blobs("analysis", ["demo"]) == {}
    assert not (cache_root / CACHE_DB).exists()


def test_cache_key_is_stable_for_dict_order() -> None:
    assert cache_key({"a": 1, "b": 2}) == cache_key({"b": 2, "a": 1})


def test_cache_key_changes_when_content_changes() -> None:
    assert cache_key({"a": 1}) != cache_key({"a": 2})


def test_cache_key_is_stable_for_nested_dict_order() -> None:
    left: Json = {"kind": "demo", "meta": {"a": 1, "b": 2}}
    right: Json = {"meta": {"b": 2, "a": 1}, "kind": "demo"}

    assert cache_key(left) == cache_key(right)


def test_get_blobs_returns_hit_payloads_and_omits_misses(
    cache_factory: Callable[..., PersistentCache],
) -> None:
    cache = cache_factory()
    cache.set_blob("relations", "left", cache_blob({"result": "no_relation"}))
    cache.set_blob("relations", "right", cache_blob({"result": "relation_pair"}))
    cache.close()

    reopened = cache_factory()
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


def test_set_blobs_persists_multiple_payloads(
    cache_factory: Callable[..., PersistentCache],
) -> None:
    cache = cache_factory()

    cache.set_blobs(
        "relations",
        {
            "left": cache_blob({"result": "no_relation"}),
            "right": cache_blob({"result": "relation_pair"}),
        },
    )
    cache.close()

    reopened = cache_factory()
    payloads = reopened.get_blobs("relations", ["left", "right"])

    assert load_cache_blob(payloads["left"]) == {"result": "no_relation"}
    assert load_cache_blob(payloads["right"]) == {"result": "relation_pair"}
    _assert_namespace_stats(
        reopened.run_stats(),
        "relations",
        {"gets": 2, "hits": 2, "misses": 0, "sets": 0},
    )


def test_persistent_cache_namespaces_are_isolated(
    cache_factory: Callable[..., PersistentCache],
) -> None:
    cache = cache_factory()
    cache.set_blob("left", "same-key", cache_blob({"value": "left"}))
    cache.set_blob("right", "same-key", cache_blob({"value": "right"}))
    cache.close()

    reopened = cache_factory()
    assert reopened.get_blob_object("left", "same-key") == {"value": "left"}
    assert reopened.get_blob_object("right", "same-key") == {"value": "right"}


def test_persistent_cache_overwrites_existing_blob(
    cache_factory: Callable[..., PersistentCache],
) -> None:
    cache = cache_factory()
    cache.set_blob("analysis", "key", cache_blob({"version": 1}))
    cache.set_blob("analysis", "key", cache_blob({"version": 2}))
    cache.close()

    reopened = cache_factory()
    assert reopened.get_blob_object("analysis", "key") == {"version": 2}


def test_get_blobs_with_empty_keys_returns_empty_mapping(
    cache_factory: Callable[..., PersistentCache],
) -> None:
    cache = cache_factory()

    assert cache.get_blobs("analysis", []) == {}
    assert cache.run_stats()["gets"] == 0


def test_persistent_cache_memoizes_blob_objects(
    cache_factory: Callable[..., PersistentCache],
) -> None:
    cache = cache_factory()
    payload = {"result": "relation_pairs"}
    blob = cache_blob(payload)
    cache.set_blob("relations", "group", blob)
    cache.close()

    reopened = cache_factory()
    first = reopened.get_blob_object("relations", "group")
    second = reopened.get_blob_object("relations", "group")

    assert first == payload
    assert second is first
    stats = reopened.run_stats()
    _assert_namespace_stats(stats, "relations", {"gets": 2, "hits": 2, "misses": 0, "sets": 0})
    _assert_blob_load_stats(stats, "relations", blob_size=len(blob))


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
    blob_size: int,
) -> None:
    namespace_stats = stats["namespaces"][namespace]
    assert namespace_stats["blob_load_count"] == 1
    assert namespace_stats["blob_load_bytes"] == blob_size
    assert namespace_stats["blob_load_ms"] >= 0
    assert namespace_stats["blob_load_avg_ms"] >= 0
    assert namespace_stats["blob_load_max_ms"] >= 0
