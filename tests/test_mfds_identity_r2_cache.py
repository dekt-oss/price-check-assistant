from __future__ import annotations

from types import SimpleNamespace

from purchase_price.services import mfds_identity_r2 as identity_r2


def _settings():
    return SimpleNamespace(
        resolved_r2_endpoint_url="https://example.r2.cloudflarestorage.com",
        resolved_r2_bucket_name="bucket",
    )


def test_validated_identity_cache_file_is_hashed_only_once(tmp_path, monkeypatch) -> None:
    path = tmp_path / "identity.sqlite"
    path.write_bytes(b"sqlite-data")
    sha256 = "a" * 64
    identity_r2._VALIDATED_CACHE_FILES.clear()

    calls = {"count": 0}

    def fake_sha256_file(_path):
        calls["count"] += 1
        return sha256

    monkeypatch.setattr(identity_r2, "_sha256_file", fake_sha256_file)

    assert identity_r2._cache_file_is_valid(path, sha256) is True
    assert identity_r2._cache_file_is_valid(path, sha256) is True
    assert calls["count"] == 1


def test_runtime_identity_path_cache_skips_repeated_r2_pointer_read(
    tmp_path,
    monkeypatch,
) -> None:
    sha256 = "b" * 64
    cache_dir = tmp_path / "mfds"
    cache_dir.mkdir()
    destination = cache_dir / f"{sha256}.sqlite"
    destination.write_bytes(b"identity-index")

    pointer_reads = {"count": 0}

    class FakeStateStore:
        def read_json(self, name):
            assert name == identity_r2.MFDS_IDENTITY_POINTER_STATE
            pointer_reads["count"] += 1
            return {
                "schema": identity_r2.MFDS_IDENTITY_POINTER_SCHEMA,
                "key": f"derived/v1/mfds-identity/{sha256}.sqlite.gz",
                "sha256": sha256,
                "stored_bytes": 10,
                "uncompressed_bytes": destination.stat().st_size,
            }

    monkeypatch.setattr(identity_r2, "_CACHE_DIR", cache_dir)
    monkeypatch.setattr(
        identity_r2,
        "R2OperationalStateStore",
        SimpleNamespace(from_settings=lambda _settings: FakeStateStore()),
    )
    monkeypatch.setattr(identity_r2, "_sha256_file", lambda _path: sha256)
    identity_r2._VALIDATED_CACHE_FILES.clear()
    identity_r2._LOCAL_INDEX_PATH_CACHE.clear()

    settings = _settings()
    first = identity_r2._local_index_path(settings)
    second = identity_r2._local_index_path(settings)

    assert first == destination
    assert second == destination
    assert pointer_reads["count"] == 1


def test_runtime_identity_path_cache_invalidates_changed_local_file(tmp_path) -> None:
    path = tmp_path / "identity.sqlite"
    path.write_bytes(b"first")
    sha256 = "c" * 64
    settings = _settings()
    key = identity_r2._runtime_cache_key(settings)

    identity_r2._VALIDATED_CACHE_FILES.clear()
    identity_r2._LOCAL_INDEX_PATH_CACHE.clear()
    identity_r2._remember_validated_cache(path, sha256)
    identity_r2._LOCAL_INDEX_PATH_CACHE[key] = (10_000.0, path, sha256)

    assert identity_r2._cached_local_index_path(settings, now=1.0) == path

    path.write_bytes(b"changed")
    assert identity_r2._cached_local_index_path(settings, now=2.0) is None
