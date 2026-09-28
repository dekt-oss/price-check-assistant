from pathlib import Path

from sqlalchemy import create_engine as sqlalchemy_create_engine

from purchase_price.db import Base
from purchase_price.schemas import ProductQuery
from purchase_price.services import track_b_r2_quote_index as module


class FakeSettings:
    r2_configured = True


def test_track_b_snapshot_reuses_one_pointer_engine_and_session(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "track-b.sqlite"
    seed_engine = sqlalchemy_create_engine(f"sqlite+pysqlite:///{db_path}")
    Base.metadata.create_all(seed_engine)
    seed_engine.dispose()

    path_calls = 0
    engine_calls = 0

    def fake_local_index_path(_settings):
        nonlocal path_calls
        path_calls += 1
        return db_path

    def counted_create_engine(*args, **kwargs):
        nonlocal engine_calls
        engine_calls += 1
        return sqlalchemy_create_engine(*args, **kwargs)

    monkeypatch.setattr(module, "_local_index_path", fake_local_index_path)
    monkeypatch.setattr(module, "create_engine", counted_create_engine)

    with module.open_track_b_serving_snapshot(settings=FakeSettings()) as snapshot:
        first = snapshot.lookup(
            ProductQuery(product_name="심장충격기", model_name="DFM100"),
            quote_unit_price=None,
        )
        second = snapshot.lookup(
            ProductQuery(product_name="심장충격기", model_name="DFM200"),
            quote_unit_price=None,
        )

    assert path_calls == 1
    assert engine_calls == 1
    assert first.status == "not_ingested"
    assert second.status == "not_ingested"
    assert snapshot.session is None
    assert snapshot.engine is None


def test_track_b_snapshot_batches_many_model_summaries_without_reopening_index(
    monkeypatch, tmp_path: Path
) -> None:
    db_path = tmp_path / "track-b-batch.sqlite"
    seed_engine = sqlalchemy_create_engine(f"sqlite+pysqlite:///{db_path}")
    Base.metadata.create_all(seed_engine)
    seed_engine.dispose()

    path_calls = 0
    engine_calls = 0

    def fake_local_index_path(_settings):
        nonlocal path_calls
        path_calls += 1
        return db_path

    def counted_create_engine(*args, **kwargs):
        nonlocal engine_calls
        engine_calls += 1
        return sqlalchemy_create_engine(*args, **kwargs)

    monkeypatch.setattr(module, "_local_index_path", fake_local_index_path)
    monkeypatch.setattr(module, "create_engine", counted_create_engine)

    queries = tuple(
        ProductQuery(product_name="제습기", model_name=f"MA-{index:04d}")
        for index in range(1, 51)
    )
    with module.open_track_b_serving_snapshot(settings=FakeSettings()) as snapshot:
        results = snapshot.lookup_model_summaries(queries)

    assert len(results) == 50
    assert all(result.status == "not_ingested" for result in results)
    assert path_calls == 1
    assert engine_calls == 1
