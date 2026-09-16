from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from test_track_b_db_quote_comparison import _item, _page

from purchase_price.db import Base
from purchase_price.models import TrackBDeliveryLine
from purchase_price.scripts.validate_g2b_track_b_quote_upload_live import validate_quote_files
from purchase_price.services.track_b_db_quote_comparison import ingest_track_b_page


def test_r2_derived_xlsx_extracts_and_matches_without_exposing_price_in_report(tmp_path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        ingest_track_b_page(session, _page([_item(price="90")]))
        session.commit()
        row = session.scalar(select(TrackBDeliveryLine))
        assert row is not None

        report = validate_quote_files(session, rows=[row], output_dir=tmp_path)

    assert report == {
        "quote_files_created": 1,
        "quote_files_extracted": 1,
        "quote_files_matched": 1,
        "match_grades": {"A": 1},
    }
    assert "90" not in str(report)
    assert (tmp_path / "actual-r2-derived-quote-01.xlsx").is_file()
    engine.dispose()
