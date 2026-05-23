from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from helpers import file_record as _file_record

from codeseam.adapters.languages.python.adapter import PythonAstAdapter
from codeseam.analysis import RepositoryScan, build_repository_facts
from codeseam.cache import RELATION_DETAIL_FEATURE_CACHE_NAMESPACE, PersistentCache
from codeseam.config import load_config
from codeseam.pipeline.signatures import build_signature_artifacts
from codeseam.platform import as_json_object, json_int

from .factories import FIXTURE_ROOT, audit_cache, fixture_artifacts
from .selectors import namespace_stats

EXPECTED_LOCAL_DUPLICATE_OCCURRENCES = 2


def test_signature_artifacts_skip_python_ast_parse_on_warm_cache(
    cache_factory: Callable[..., PersistentCache],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path_roles = [("warm_cache_service.py", "source")]

    first_cache = cache_factory()
    first = fixture_artifacts(path_roles, audit_cache(first_cache))
    first_cache.close()
    assert [record.core.symbol for record in first.records] == ["repeated"]

    def fail_parse(path: Path) -> object:
        raise AssertionError(f"unexpected Python AST parse for unchanged file: {path}")

    monkeypatch.setattr("codeseam.adapters.languages.python.adapter.parse_python", fail_parse)
    monkeypatch.setattr("codeseam.adapters.languages.python.signatures.parse_python", fail_parse)

    second_cache = cache_factory()
    second = fixture_artifacts(path_roles, audit_cache(second_cache))
    stats = second_cache.run_stats()

    assert [record.core.symbol for record in second.records] == ["repeated"]
    assert namespace_stats(stats, "signature_cores")["hits"] == 1
    assert namespace_stats(stats, "signature_features")["hits"] == 1
    assert namespace_stats(stats, "signature_output")["hits"] == 1
    assert namespace_stats(stats, "policy_constants")["hits"] == 1


def test_relation_detail_cache_avoids_warm_hydration(
    cache_factory: Callable[..., PersistentCache],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path_roles = [("small_structural_duplicate.py", "source")]

    first_cache = cache_factory()
    fixture_artifacts(path_roles, audit_cache(first_cache))
    first_cache.close()

    def fail_hydration(self: PythonAstAdapter, request: object) -> object:
        raise AssertionError("warm relation-detail cache should bypass adapter hydration")

    original_get_blob_object = PersistentCache.get_blob_object
    original_get_blobs = PersistentCache.get_blobs
    batch_reads: list[tuple[str, ...]] = []

    def reject_relation_detail_item_read(
        self: PersistentCache,
        namespace: str,
        key: str,
    ) -> object | None:
        if namespace == RELATION_DETAIL_FEATURE_CACHE_NAMESPACE:
            raise AssertionError("relation-detail cache should use batched reads")
        return original_get_blob_object(self, namespace, key)

    def capture_relation_detail_batch_read(
        self: PersistentCache,
        namespace: str,
        keys: list[str] | tuple[str, ...],
    ) -> dict[str, bytes]:
        if namespace == RELATION_DETAIL_FEATURE_CACHE_NAMESPACE:
            batch_reads.append(tuple(keys))
        return original_get_blobs(self, namespace, keys)

    monkeypatch.setattr(PythonAstAdapter, "hydrate_relation_detail", fail_hydration)
    monkeypatch.setattr(PersistentCache, "get_blob_object", reject_relation_detail_item_read)
    monkeypatch.setattr(PersistentCache, "get_blobs", capture_relation_detail_batch_read)

    second_cache = cache_factory()
    fixture_artifacts(path_roles, audit_cache(second_cache))
    stats = second_cache.run_stats()

    relation_detail_stats = as_json_object(
        as_json_object(stats.get("namespaces")).get("relation_detail_features")
    )
    assert batch_reads
    assert all(len(keys) > 1 for keys in batch_reads)
    assert json_int(relation_detail_stats.get("hits")) > 0
    assert json_int(relation_detail_stats.get("misses")) == 0


@pytest.mark.parametrize(
    ("fixture", "language", "symbol"),
    [
        pytest.param("intra_function_duplicate.py", "Python", "completed_result", id="python"),
        pytest.param(
            "intra_function_duplicate.ts",
            "TypeScript",
            "completedResult",
            id="typescript",
        ),
    ],
)
def test_intra_function_duplicate_blocks_are_collected(
    fixture: str,
    language: str,
    symbol: str,
) -> None:
    facts = build_repository_facts(
        RepositoryScan(
            records=[_file_record(fixture, language=language)],
            selected_paths=[fixture],
        )
    )
    artifacts = build_signature_artifacts(load_config(FIXTURE_ROOT), facts, [])
    signature = next(item for item in artifacts.records if item.core.symbol == symbol)

    blocks = signature.core.intra_function_duplicate_blocks

    assert len(blocks) == 1
    assert len(blocks[0].occurrences) == EXPECTED_LOCAL_DUPLICATE_OCCURRENCES
