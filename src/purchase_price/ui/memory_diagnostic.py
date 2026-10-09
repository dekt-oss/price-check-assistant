"""Read-only memory snapshot for ``Home.py?_memdiag=1``.

On 2026-10-09 the Production app went over Streamlit Cloud's resource limit twice although the
Python process itself stays near 110-170 MB (measured with every page and a search). The ~3 GB of
SQLite index files in the temp directory are the suspect: a container counts file-backed memory
(page cache, tmpfs) against the limit, and a refresh briefly holds the old and the new copy.
This reports both views side by side so the next incident has numbers instead of a guess.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

# Runtime marker: pages/1_대시보드.py reloads a retained pre-#329 copy that lacks it.
SEARCH_INDEX_V1 = True
CACHE_DIR_NAMES = ("price-check-track-b", "price-check-mfds", "price-check-mfds-item-status")
_CGROUP_V2 = Path("/sys/fs/cgroup")
_CGROUP_V1 = Path("/sys/fs/cgroup/memory")


@dataclass(frozen=True)
class MemorySnapshot:
    process_rss_mb: float | None
    container_used_mb: float | None
    container_limit_mb: float | None
    container_file_mb: float | None  # page cache / tmpfs share of the container figure
    cache_files_mb: dict[str, float]
    # e.g. "3.45.1 부분검색 색인 사용 가능": whether this runtime can use the Track B search side index.
    sqlite_search: str | None = None


def _sqlite_search() -> str | None:
    try:
        from purchase_price.services.track_b_search_index import sqlite_search_support

        version, supported = sqlite_search_support()
    except Exception:  # noqa: BLE001 - diagnostics never break the page
        return None
    return f"{version} 부분검색 색인 {'사용 가능' if supported else '사용 불가'}"


def _read_int(path: Path) -> int | None:
    try:
        text = path.read_text(encoding="ascii").strip()
        return int(text) if text.isdigit() else None
    except (OSError, ValueError):
        return None


def _stat_value(path: Path, key: str) -> int | None:
    try:
        for line in path.read_text(encoding="ascii").splitlines():
            name, _, value = line.partition(" ")
            if name == key and value.strip().isdigit():
                return int(value)
    except (OSError, ValueError):
        pass
    return None


def _container_figures() -> tuple[int | None, int | None, int | None]:
    """(used, limit, file-backed) bytes from cgroup v2, else v1; Nones where unreadable."""

    used = _read_int(_CGROUP_V2 / "memory.current")
    if used is not None:
        return used, _read_int(_CGROUP_V2 / "memory.max"), _stat_value(_CGROUP_V2 / "memory.stat", "file")
    used = _read_int(_CGROUP_V1 / "memory.usage_in_bytes")
    if used is not None:
        return used, _read_int(_CGROUP_V1 / "memory.limit_in_bytes"), _stat_value(_CGROUP_V1 / "memory.stat", "cache")
    return None, None, None


def _process_rss() -> int | None:
    try:
        import psutil

        return psutil.Process().memory_info().rss
    except Exception:  # noqa: BLE001 - psutil is optional in Production
        pass
    try:
        for line in Path("/proc/self/status").read_text(encoding="ascii").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def _dir_bytes(path: Path) -> int:
    total = 0
    try:
        for entry in os.scandir(path):
            if entry.is_file(follow_symlinks=False):
                total += entry.stat(follow_symlinks=False).st_size
    except OSError:
        return 0
    return total


def _mb(value: int | None) -> float | None:
    return None if value is None else round(value / 1_000_000, 1)


def take_snapshot() -> MemorySnapshot:
    used, limit, file_backed = _container_figures()
    root = Path(tempfile.gettempdir())
    return MemorySnapshot(
        process_rss_mb=_mb(_process_rss()),
        container_used_mb=_mb(used),
        # cgroup v2 reports "max" (no limit) as text, which _read_int turns into None.
        container_limit_mb=_mb(limit),
        container_file_mb=_mb(file_backed),
        cache_files_mb={name: _mb(_dir_bytes(root / name)) or 0.0 for name in CACHE_DIR_NAMES},
        sqlite_search=_sqlite_search(),
    )


def format_snapshot(snapshot: MemorySnapshot) -> str:
    def show(value: float | None) -> str:
        return "읽을 수 없음" if value is None else f"{value:,.0f} MB"

    files = " · ".join(f"{name.removeprefix('price-check-')} {size:,.0f} MB" for name, size in snapshot.cache_files_mb.items())
    return (
        f"MEMORY_DIAGNOSTIC 프로세스 {show(snapshot.process_rss_mb)} · "
        f"컨테이너 사용 {show(snapshot.container_used_mb)} / 한도 {show(snapshot.container_limit_mb)} "
        f"(그중 파일 캐시 {show(snapshot.container_file_mb)}) · 임시폴더 인덱스 파일 {files}"
        f" · SQLite {snapshot.sqlite_search or '읽을 수 없음'}"
    )
