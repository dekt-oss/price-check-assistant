from __future__ import annotations

from pathlib import Path

from purchase_price.ui import memory_diagnostic as md


def test_snapshot_counts_index_files_and_formats_without_cgroup(tmp_path: Path, monkeypatch) -> None:
    folder = tmp_path / "price-check-mfds"
    folder.mkdir()
    (folder / "a.sqlite").write_bytes(b"x" * 2_000_000)
    monkeypatch.setattr(md.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(md, "_container_figures", lambda: (None, None, None))

    snapshot = md.take_snapshot()

    assert snapshot.cache_files_mb["price-check-mfds"] == 2.0
    assert snapshot.cache_files_mb["price-check-track-b"] == 0.0
    text = md.format_snapshot(snapshot)
    assert text.startswith("MEMORY_DIAGNOSTIC") and "읽을 수 없음" in text and "mfds 2 MB" in text


def test_cgroup_v2_figures_are_read(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "memory.current").write_text("3000000000\n")
    (tmp_path / "memory.max").write_text("max\n")
    (tmp_path / "memory.stat").write_text("anon 100\nfile 2900000000\n")
    monkeypatch.setattr(md, "_CGROUP_V2", tmp_path)

    assert md._container_figures() == (3_000_000_000, None, 2_900_000_000)
