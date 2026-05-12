from __future__ import annotations

import pickle


def cache_blob(payload: object) -> bytes:
    return pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL)


def load_cache_blob(payload: bytes) -> object:
    return pickle.loads(payload)
