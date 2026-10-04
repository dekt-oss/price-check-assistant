from pathlib import Path


def test_mfds_sync_uses_ttl_lock_around_collector() -> None:
    source = Path("src/purchase_price/scripts/sync_mfds_identity_index.py").read_text(
        encoding="utf-8"
    )

    assert "COLLECTION_LOCK_TTL_SECONDS = 3 * 60 * 60" in source
    assert "state_store.acquire_lock(" in source
    assert '"status": "LOCK_HELD"' in source
    assert "state_store.release_lock(" in source


def test_mfds_serving_pointer_is_published_only_after_complete_index_upload() -> None:
    source = Path("src/purchase_price/scripts/sync_mfds_identity_index.py").read_text(
        encoding="utf-8"
    )

    upload = source.index("ref = artifact_store.put_sqlite(db_path)")
    pointer = source.index("state_store.write_json(MFDS_IDENTITY_POINTER_STATE, pointer_payload)")
    cleanup = source.index("artifact_store.delete(stale_retained_key)")

    assert upload < pointer < cleanup
    assert '"previous_key": previous_ref.key if previous_ref is not None else None' in source
    assert "artifact_store.delete(previous_ref.key)" not in source


def test_dashboard_reuses_one_track_b_snapshot_for_crosslinks() -> None:
    source = Path("pages/1_대시보드.py").read_text(encoding="utf-8")

    assert "with open_track_b_serving_snapshot() as track_b_snapshot:" in source
    assert "track_b_snapshot.lookup(" in source
    assert "lookup_track_b_quote_from_r2" not in source


def test_dashboard_refreshes_stale_mfds_identity_r2_adapter() -> None:
    source = Path("pages/1_대시보드.py").read_text(encoding="utf-8")

    assert "from purchase_price.services import mfds_identity_r2 as mfds_identity_r2_service" in source
    assert "def _mfds_identity_r2_runtime(" in source
    assert 'hasattr(module, "_LOCAL_INDEX_PATH_CACHE")' in source
    assert "importlib.reload(module)" in source
    assert "_lookup_mfds_identity_runtime(lookup_key)" in source
    assert "_lookup_same_mfds_product_runtime(identity_product)" in source
    assert 'id="purchase-workspace-runtime-v8"' in source
