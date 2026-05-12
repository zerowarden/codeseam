from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from codeseam.cache.blobs import cache_blob, load_cache_blob
from codeseam.cache.store import PersistentCache


class CacheCodec[T](Protocol):
    namespace: str

    def dump(self, value: T) -> object: ...

    def load(self, value: object) -> T | None: ...


@dataclass
class CacheWriteBuffer:
    _payloads_by_namespace: dict[str, dict[str, bytes]] = field(default_factory=dict)

    def add[T](self, codec: CacheCodec[T], key: str, value: T) -> None:
        self._payloads_by_namespace.setdefault(codec.namespace, {})[key] = cache_blob(
            codec.dump(value)
        )

    def flush(self, cache: PersistentCache) -> None:
        for namespace, payloads in self._payloads_by_namespace.items():
            cache.set_blobs(namespace, payloads)
        self._payloads_by_namespace.clear()


@dataclass(frozen=True, slots=True)
class Cache[T]:
    persistent: PersistentCache
    codec: CacheCodec[T]
    write_buffer: CacheWriteBuffer | None = None

    def get(self, key: str) -> T | None:
        return self.codec.load(self.persistent.get_blob_object(self.codec.namespace, key))

    def get_many(self, keys: Sequence[str]) -> dict[str, T]:
        blobs = self.persistent.get_blobs(self.codec.namespace, keys)
        values: dict[str, T] = {}
        for key, blob in blobs.items():
            try:
                raw = load_cache_blob(blob)
            except Exception:
                continue
            value = self.codec.load(raw)
            if value is not None:
                values[key] = value
        return values

    def set(self, key: str, value: T) -> None:
        if self.write_buffer is not None:
            self.write_buffer.add(self.codec, key, value)
            return
        self.persistent.set_blob(
            self.codec.namespace,
            key,
            cache_blob(self.codec.dump(value)),
        )

    def set_many(self, values_by_key: Mapping[str, T]) -> None:
        if not values_by_key:
            return
        if self.write_buffer is not None:
            for key, value in values_by_key.items():
                self.write_buffer.add(self.codec, key, value)
            return
        self.persistent.set_blobs(
            self.codec.namespace,
            {key: cache_blob(self.codec.dump(value)) for key, value in values_by_key.items()},
        )


__all__ = ["Cache", "CacheCodec", "CacheWriteBuffer"]
