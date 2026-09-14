from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from test_track_b_db_quote_comparison import _item, _page

from purchase_price.db import Base
from purchase_price.models import TrackBDeliveryLine
from purchase_price.scripts.import_g2b_track_b_r2_to_db import TrackBImportFailure, run


class FakeReader:
    def __init__(self, *, fail_second: bool = False) -> None:
        self.keys = [
            "raw/v1/getSpcifyPrdlstPrcureInfoList-page/01.json.gz",
            "raw/v1/getSpcifyPrdlstPrcureInfoList-page/02.json.gz",
        ]
        self.fail_second = fail_second
        self.list_calls: list[str | None] = []

    def list_public_json_page(self, *, source_operation: str, limit: int, after_key: str | None):
        assert source_operation == "getSpcifyPrdlstPrcureInfoList-page"
        self.list_calls.append(after_key)
        keys = [key for key in self.keys if after_key is None or key > after_key][:limit]
        return SimpleNamespace(
            objects=tuple(SimpleNamespace(key=key, payload_hash="a" * 64) for key in keys),
            has_more=False,
            next_cursor=keys[-1] if keys else None,
        )

    def get_public_json(self, obj):
        if self.fail_second and obj.key.endswith("02.json.gz"):
            raise ValueError("corrupt R2 object")
        change = "00" if obj.key.endswith("01.json.gz") else "01"
        return _page([_item(change=change)]).payload


def test_import_commits_each_object_and_resumes_without_duplicate_rows() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    reader = FakeReader(fail_second=True)

    with pytest.raises(TrackBImportFailure) as error:
        run(reader=reader, session_factory=factory, limit=2)
    assert error.value.resume_cursor == reader.keys[0]
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(TrackBDeliveryLine)) == 1

    reader.fail_second = False
    resumed = run(reader=reader, session_factory=factory, limit=2, cursor=error.value.resume_cursor)
    assert resumed["inserted"] == 1
    assert resumed["resume_cursor"] == reader.keys[1]
    replay = run(reader=reader, session_factory=factory, limit=2)
    assert replay["inserted"] == 0
    assert replay["replayed"] == 2
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(TrackBDeliveryLine)) == 2
    engine.dispose()
