from __future__ import annotations

import os
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codeseam.adapters.languages.tests_matcher import LanguageTestMatcher, test_matchers_for_repo
from codeseam.adapters.repository.scan_manifest import FileContentSummary, ScanManifest
from codeseam.analysis import FileRecord, classify_path, detect_language, is_analysis_language
from codeseam.platform import (
    PROJECT_DIR,
    GlobMatcher,
    is_binary,
    line_count,
    matches_any,
    sha256_bytes,
)
from codeseam.platform.files import BINARY_PROBE_BYTES

TOP_SKIPPED_GROUPS = 8
GITIGNORE_GROUP = "gitignore"
DEFAULT_GENERATED_EXCLUDES = (
    # Generated source trees are usually rebuild outputs. They can be large and
    # structurally repetitive, so excluding them before extraction protects both
    # runtime and recommendation quality.
    "generated/**",
    "**/generated/**",
    "**/*.generated.*",
    # Yarn Plug'n'Play emits loader/runtime files such as `.pnp.cjs` and
    # `.pnp.loader.mjs`. They are repository-local generated artifacts, not
    # direct refactor targets.
    ".pnp.*",
)
DEFAULT_EXCLUDES = (
    ".git/**",
    f"{PROJECT_DIR}/**",
    ".yarn/**",
    ".cache/**",
    ".venv/**",
    "venv/**",
    "build/**",
    "coverage/**",
    "dist/**",
    "fixtures/**",
    "**/fixtures/**",
    "__fixtures__/**",
    "**/__fixtures__/**",
    ".next/**",
    ".nuxt/**",
    "__pycache__/**",
    "node_modules/**",
    "vendor/**",
    "**/*.min.js",
    "**/*.map",
    "**/*.lock",
    "uv.lock",
    *DEFAULT_GENERATED_EXCLUDES,
)


@dataclass(frozen=True, slots=True)
class GitIgnoredPaths:
    directories: frozenset[str]
    files: frozenset[str]

    def matches(self, rel: str, *, include_file: bool) -> bool:
        return (include_file and rel in self.files) or self._ignored_by_parent(rel)

    def _ignored_by_parent(self, rel: str) -> bool:
        parts = rel.split("/")
        return any(
            "/".join(parts[:index]) in self.directories for index in range(1, len(parts) + 1)
        )


def select_files(
    repo_root: Path,
    selection_config: dict[str, Any],
    scan_manifest: ScanManifest | None = None,
) -> tuple[list[FileRecord], list[str]]:
    includes = list(selection_config.get("include", ["**/*"]))
    excludes = [*DEFAULT_EXCLUDES, *list(selection_config.get("exclude", []))]
    include_matcher = GlobMatcher.from_patterns(includes)
    exclude_matcher = GlobMatcher.from_patterns(excludes)
    git_ignored = _git_ignored_paths(repo_root)
    test_matchers = test_matchers_for_repo(repo_root)
    records: list[FileRecord] = []
    selected_paths: list[str] = []

    for rel, path in _walk_files(repo_root, exclude_matcher, git_ignored):
        if not include_matcher.matches(rel):
            continue
        record = _record_for(path, Path(rel), test_matchers, scan_manifest)
        if record is None:
            continue
        records.append(record)
        if is_analysis_language(record.language):
            selected_paths.append(rel)

    return records, selected_paths


def explain_file_selection(
    repo_root: Path,
    selection_config: dict[str, Any],
) -> dict[str, object]:
    includes = list(selection_config.get("include", ["**/*"]))
    excludes = [*DEFAULT_EXCLUDES, *list(selection_config.get("exclude", []))]
    git_ignored = _git_ignored_paths(repo_root)
    analysed = 0
    skipped = 0
    groups: Counter[str] = Counter()
    root = repo_root.resolve()

    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        rel_dir = "" if current == root else current.relative_to(root).as_posix()
        kept_dirs: list[str] = []
        for dirname in sorted(dirnames):
            rel = f"{rel_dir}/{dirname}".lstrip("/")
            pattern = _matched_exclude(rel, excludes, is_dir=True)
            if pattern or git_ignored.matches(rel, include_file=False):
                count = _count_files(current / dirname, root)
                skipped += count
                groups[_skip_group(rel, pattern) if pattern else GITIGNORE_GROUP] += count
            else:
                kept_dirs.append(dirname)
        dirnames[:] = kept_dirs

        for filename in sorted(filenames):
            path = current / filename
            if path.is_symlink() and not _is_internal_symlink(path, root):
                skipped += 1
                groups["external symlinks"] += 1
                continue
            rel = f"{rel_dir}/{filename}".lstrip("/")
            pattern = _matched_exclude(rel, excludes, is_dir=False)
            if pattern:
                skipped += 1
                groups[_skip_group(rel, pattern)] += 1
                continue
            if git_ignored.matches(rel, include_file=True):
                skipped += 1
                groups[GITIGNORE_GROUP] += 1
                continue
            if not matches_any(rel, includes):
                skipped += 1
                groups["not included"] += 1
                continue
            if is_binary(path):
                skipped += 1
                groups["binary files"] += 1
                continue
            if is_analysis_language(detect_language(Path(rel))):
                analysed += 1
            else:
                skipped += 1
                groups["non-analysis files"] += 1

    return {
        "analysed": analysed,
        "skipped": skipped,
        "top_skipped_groups": [
            {"group": group, "count": count}
            for group, count in groups.most_common(TOP_SKIPPED_GROUPS)
            if count > 0
        ],
    }


def _walk_files(
    repo_root: Path,
    excludes: GlobMatcher,
    git_ignored: GitIgnoredPaths,
) -> list[tuple[str, Path]]:
    root = repo_root.resolve()
    files: list[tuple[str, Path]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        rel_dir = "" if current == root else current.relative_to(root).as_posix()
        dirnames[:] = [
            dirname
            for dirname in sorted(dirnames)
            if not _excluded_dir(f"{rel_dir}/{dirname}".lstrip("/"), excludes, git_ignored)
        ]
        for filename in sorted(filenames):
            path = current / filename
            if path.is_symlink() and not _is_internal_symlink(path, root):
                continue
            rel = f"{rel_dir}/{filename}".lstrip("/")
            if excludes.matches(rel) or git_ignored.matches(rel, include_file=True):
                continue
            files.append((rel, path))
    return files


def _excluded_dir(rel: str, excludes: GlobMatcher, git_ignored: GitIgnoredPaths) -> bool:
    return excludes.matches_dir(rel) or git_ignored.matches(rel, include_file=False)


def _git_ignored_paths(repo_root: Path) -> GitIgnoredPaths:
    """Return Git-standard ignored paths as an extra filter.

    Codeseam's configured/default excludes are always applied separately. This
    helper only adds Git's ignore view when available, including nested
    `.gitignore`, `.git/info/exclude`, and global `core.excludesFile` rules.
    """
    command = [
        "git",
        "-C",
        str(repo_root.resolve()),
        "ls-files",
        "--others",
        "--ignored",
        "--exclude-standard",
        "--directory",
        "-z",
    ]
    try:
        result = subprocess.run(command, check=False, capture_output=True)
    except (OSError, subprocess.SubprocessError):
        return GitIgnoredPaths(frozenset(), frozenset())
    if result.returncode != 0:
        return GitIgnoredPaths(frozenset(), frozenset())
    entries = [
        entry
        for entry in result.stdout.decode("utf-8", errors="surrogateescape").split("\0")
        if entry
    ]
    return GitIgnoredPaths(
        directories=frozenset(entry.rstrip("/") for entry in entries if entry.endswith("/")),
        files=frozenset(entry for entry in entries if not entry.endswith("/")),
    )


def _matched_exclude(rel: str, excludes: list[str], *, is_dir: bool) -> str:
    for pattern in excludes:
        if matches_any(rel, [pattern]) or (is_dir and matches_any(f"{rel}/__dir__", [pattern])):
            return pattern
    return ""


def _count_files(path: Path, root: Path) -> int:
    count = 0
    for dirpath, _, filenames in os.walk(path):
        current = Path(dirpath)
        for filename in filenames:
            file_path = current / filename
            if not file_path.is_symlink() or _is_internal_symlink(file_path, root):
                count += 1
    return count


def _skip_group(rel: str, pattern: str) -> str:
    cleaned = pattern.removeprefix("**/").removesuffix("/**")
    if cleaned and not any(char in cleaned for char in "*?[]"):
        parts = Path(cleaned).parts
        if len(parts) > 1 and "." in parts[-1]:
            return f"{parts[0]}/"
        return cleaned.rstrip("/") + "/"
    parts = Path(rel).parts
    return f"{parts[0]}/" if len(parts) > 1 else pattern


def _is_internal_symlink(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root)
    except (OSError, ValueError):
        return False
    return True


def _record_for(
    path: Path,
    relative: Path,
    test_matchers: dict[str, LanguageTestMatcher],
    scan_manifest: ScanManifest | None,
) -> FileRecord | None:
    rel = relative.as_posix()
    language = detect_language(relative)
    language_tests = test_matchers.get(language)
    classification = classify_path(
        relative,
        language_test_path=language_tests.matches_path if language_tests else None,
    )
    if not is_analysis_language(language):
        stat = path.stat()
        return FileRecord(
            path=rel,
            language=language,
            size_bytes=stat.st_size,
            line_count=0,
            content_hash="",
            role=classification.role,
            is_generated=classification.is_generated,
            is_vendor=classification.is_vendor,
            is_test=classification.is_test,
            is_build_output=classification.is_build_output,
        )
    stat = path.stat()
    summary = scan_manifest.content_summary(rel, stat) if scan_manifest is not None else None
    if summary is None:
        summary = _content_summary(path)
    if summary is None:
        return None
    if scan_manifest is not None:
        scan_manifest.remember(rel, stat, summary)
    return FileRecord(
        path=rel,
        language=language,
        size_bytes=summary.size_bytes,
        line_count=summary.line_count,
        content_hash=summary.content_hash,
        role=classification.role,
        is_generated=classification.is_generated,
        is_vendor=classification.is_vendor,
        is_test=classification.is_test,
        is_build_output=classification.is_build_output,
    )


def _content_summary(path: Path) -> FileContentSummary | None:
    data = path.read_bytes()
    if b"\0" in data[:BINARY_PROBE_BYTES]:
        return None
    return FileContentSummary(
        size_bytes=len(data),
        line_count=line_count(data),
        content_hash=sha256_bytes(data),
    )
