from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FileRecord:
    path: str
    language: str
    size_bytes: int
    line_count: int
    content_hash: str
    role: str
    is_generated: bool
    is_vendor: bool
    is_test: bool
    is_build_output: bool


@dataclass(frozen=True)
class RepositoryManifest:
    path: str
    kind: str


@dataclass(frozen=True)
class RepositoryScan:
    records: list[FileRecord]
    selected_paths: list[str]
    manifests: tuple[RepositoryManifest, ...] = field(default_factory=tuple)


__all__ = ["FileRecord", "RepositoryManifest", "RepositoryScan"]
