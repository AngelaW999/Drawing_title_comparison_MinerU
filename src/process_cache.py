from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Iterable, Set


_LOCK = Lock()
_GENERATED_CACHE_FILES: Set[Path] = set()


def _normalize(path: Path | str) -> Path:
    return Path(path).expanduser().resolve()


def register_cache_file(path: Path | str) -> None:
    p = _normalize(path)
    if ".cache" not in p.parts:
        return
    with _LOCK:
        _GENERATED_CACHE_FILES.add(p)


def snapshot_generated_cache_files() -> list[Path]:
    with _LOCK:
        return sorted(_GENERATED_CACHE_FILES)


def _remove_empty_parent_dirs(start: Path, stop_dir: Path) -> None:
    cur = start
    while cur != stop_dir:
        try:
            cur.rmdir()
        except Exception:
            break
        parent = cur.parent
        if parent == cur:
            break
        cur = parent


def cleanup_generated_cache_files(paths: Iterable[Path] | None = None) -> int:
    files = list(paths) if paths is not None else snapshot_generated_cache_files()
    deleted = 0

    for p in files:
        try:
            p = _normalize(p)
            if not p.exists() or not p.is_file():
                continue

            cache_root = None
            parts = list(p.parts)
            if ".cache" in parts:
                idx = parts.index(".cache")
                cache_root = Path(*parts[: idx + 1])

            p.unlink()
            deleted += 1

            if cache_root is not None:
                _remove_empty_parent_dirs(p.parent, cache_root)
        except Exception:
            continue

    with _LOCK:
        for p in files:
            _GENERATED_CACHE_FILES.discard(_normalize(p))

    return deleted
