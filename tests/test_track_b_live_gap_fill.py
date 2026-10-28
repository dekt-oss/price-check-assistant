from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from purchase_price.models import Base, TrackBDeliveryLine
from purchase_price.schemas import ProductQuery
from purchase_price.services import track_b_live_gap_fill as gap
from purchase_price.services.track_b_db_quote_comparison import TrackBQuoteComparison


def _item(
    delivery: str,
    *,
    change: str = "00",
    line: str = "1",
    title: str = "심장충격기, 나눔테크, NT-SG",
    price: str = "396000",
    when: str = "20260929",
) -> dict[str, Any]:
    return {
        "cntrctDlvrReqNo": delivery,
        "cntrctDlvrReqChgOrd": change,
        "prdctSno": line,
        "prdctClsfcNoNm": "심장충격기",
        "dtilPrdctClsfcNo": "4217210101",
        "prdctIdntNo": "24000001",
        "prdctIdntNoNm": title,
        "dtilPrdctClsfcNoNm": "심장충격기",
        "prdctUprc": price,
        "prdctQty": "1",
        "prdctUnit": "대",
        "prdctAmt": price,
        "cntrctDlvrReqDate": when,
        "corpNm": "(주)나눔테크",
        "dminsttNm": "어느보건소",
    }


class FakeClient:
    def __init__(self, pages: dict[str, list[dict[str, Any]]], fail: bool = False) -> None:
        self.pages = pages
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    def get_json(self, base_url: str, endpoint: str, **params: Any) -> dict[str, Any]:
        self.calls.append(params)
        if self.fail:
            raise TimeoutError("timed out")
        items = self.pages.get(params["dtilPrdctClsfcNo"], [])
        return {
            "response": {
                "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
                "body": {"items": items, "totalCount": len(items), "pageNo": 1, "numOfRows": 999},
            }
        }


WINDOW = (date(2026, 9, 19), date(2026, 10, 5), False)
QUERY = ProductQuery(product_name="심장충격기", model_name="NT-SG")


def test_live_gap_window() -> None:
    assert gap.live_gap_window("2026-09-18", date(2026, 10, 5)) == (
        date(2026, 9, 19),
        date(2026, 10, 5),
        False,
    )
    assert gap.live_gap_window("2026-10-05", date(2026, 10, 5)) is None
    assert gap.live_gap_window(None, date(2026, 10, 5)) is None
    assert gap.live_gap_window("not-a-date", date(2026, 10, 5)) is None
    begin, end, truncated = gap.live_gap_window("2026-01-01", date(2026, 10, 5))
    assert truncated is True
    assert (end - begin).days == gap.MAX_GAP_DAYS - 1


def test_fetch_grades_only_the_same_model_and_labels_live_rows() -> None:
    client = FakeClient(
        {
            "4217210101": [
                _item("R1"),
                _item("R2", title="심장충격기, 나눔테크, NT-381.B"),  # other model, dropped
            ]
        }
    )

    result = gap.fetch_live_gap(QUERY, detail_codes=["4217210101"], window=WINDOW, client=client)

    assert result.status == "success"
    assert result.rows_seen == 2
    assert result.request_count == 1
    assert [c.source_record_id for c in result.candidates] == ["delivery:R1|change:00|line:1"]
    assert result.candidates[0].transaction_type == gap.LIVE_TRANSACTION_TYPE
    assert result.candidates[0].price == Decimal("396000")
    params = client.calls[0]
    assert params["inqryBgnDate"] == "20260919"
    assert params["inqryEndDate"] == "20261005"
    assert "fnlCntrctDlvrReqChgOrdYn" not in params


def test_fetch_projects_latest_change_order() -> None:
    client = FakeClient(
        {"4217210101": [_item("R1", change="00", price="400000"), _item("R1", change="01", price="380000")]}
    )

    result = gap.fetch_live_gap(QUERY, detail_codes=["4217210101"], window=WINDOW, client=client)

    assert [(c.source_record_id, c.price) for c in result.candidates] == [
        ("delivery:R1|change:01|line:1", Decimal("380000"))
    ]


def test_fetch_without_codes_is_not_applicable_and_makes_no_request() -> None:
    client = FakeClient({})

    result = gap.fetch_live_gap(QUERY, detail_codes=[], window=WINDOW, client=client)

    assert result.status == "not_applicable"
    assert client.calls == []


def test_fetch_failure_is_reported_not_raised() -> None:
    result = gap.fetch_live_gap(
        QUERY, detail_codes=["4217210101"], window=WINDOW, client=FakeClient({}, fail=True)
    )

    assert result.status == "failure"
    assert result.error_type == "TimeoutError"
    assert result.candidates == ()


def test_merge_dedupes_by_delivery_line_and_newer_change_order_wins() -> None:
    live = gap.fetch_live_gap(
        QUERY,
        detail_codes=["4217210101"],
        window=WINDOW,
        client=FakeClient(
            {
                "4217210101": [
                    _item("R1", change="00"),  # same as indexed -> indexed kept
                    _item("R2", change="01", price="350000"),  # newer than indexed R2:00
                    _item("R3", when="20261001"),  # new
                ]
            }
        ),
    )
    indexed_r1 = gap.fetch_live_gap(
        QUERY,
        detail_codes=["4217210101"],
        window=WINDOW,
        client=FakeClient({"4217210101": [_item("R1"), _item("R2", change="00", price="396000")]}),
    ).candidates
    # Present them as collected rows.
    import dataclasses

    indexed = TrackBQuoteComparison(
        "success",
        tuple(dataclasses.replace(c, transaction_type="나라장터 납품요구") for c in indexed_r1),
        2,
    )

    merged = gap.merge_live_gap(indexed, live)

    by_id = {c.source_record_id: c for c in merged.candidates}
    assert set(by_id) == {
        "delivery:R1|change:00|line:1",
        "delivery:R2|change:01|line:1",
        "delivery:R3|change:00|line:1",
    }
    assert by_id["delivery:R1|change:00|line:1"].transaction_type == "나라장터 납품요구"
    assert by_id["delivery:R2|change:01|line:1"].price == Decimal("350000")
    assert merged.examined == 4


def test_merge_promotes_success_0_and_ignores_failed_live() -> None:
    empty = TrackBQuoteComparison("success_0", (), 0)
    failed = gap.TrackBLiveGapFill("failure")
    assert gap.merge_live_gap(empty, failed) is empty

    live = gap.fetch_live_gap(
        QUERY, detail_codes=["4217210101"], window=WINDOW, client=FakeClient({"4217210101": [_item("R9")]})
    )
    merged = gap.merge_live_gap(empty, live)
    assert merged.status == "success"
    assert merged.evidence_status.value == "FOUND"


def test_indexed_detail_codes_uses_model_keys_and_skips_conflicts() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[TrackBDeliveryLine.__table__])
    with Session(engine) as session:
        for index, (code, model_key, conflict) in enumerate(
            (
                ("4217210101", "ntsg", False),
                ("4217210101", "ntsg", False),
                ("4221150101", "ntsg", False),
                ("9999999999", "ntsg", True),
                ("4217210102", "other", False),
            )
        ):
            session.add(
                TrackBDeliveryLine(
                    delivery_request_number=f"R{index}",
                    change_order="00",
                    change_order_number=0,
                    product_sequence="1",
                    item_sha256="x" * 64,
                    identity_conflict=conflict,
                    identity_conflict_count=0,
                    raw_object_key="raw",
                    raw_payload_sha256="y" * 64,
                    detail_code=code,
                    model_key=model_key,
                    amount_check="MATCH",
                    api_params_json="{}",
                )
            )
        session.commit()

        assert gap.indexed_detail_codes(session, QUERY) == ("4217210101", "4221150101")
        assert gap.indexed_detail_codes(session, ProductQuery(product_name="x")) == ()


def test_dashboard_merges_live_gap_after_indexed_lookup() -> None:
    source = Path("pages/1_대시보드.py").read_text(encoding="utf-8")

    assert "live_detail_codes = indexed_detail_codes(track_b_snapshot.session, query)" in source
    assert "track_b = merge_live_gap(track_b, track_b_live)" in source
    assert '"track_b_live": track_b_live' in source
    assert 'search_timings["track_b_live"]' in source
    assert "timeout_seconds=8.0, max_retries=0" in source
    assert "나라장터 실시간 확인" in source


def test_dashboard_caption_counts_only_net_added_live_rows() -> None:
    source = Path("pages/1_대시보드.py").read_text(encoding="utf-8")

    assert "live_added = sum(" in source
    assert "모두 이미 반영" in source
    assert "수집 전 거래 {live_added}건 추가" in source


def test_live_cancelling_change_order_drops_the_collected_line() -> None:
    import dataclasses

    collected = gap.fetch_live_gap(
        QUERY, detail_codes=["4217210101"], window=WINDOW, client=FakeClient({"4217210101": [_item("R1"), _item("R2")]})
    ).candidates
    indexed = TrackBQuoteComparison(
        "success",
        tuple(dataclasses.replace(c, transaction_type="나라장터 납품요구") for c in collected),
        2,
    )
    cancel = _item("R1", change="01")
    cancel["prdctQty"] = "0"
    cancel["prdctAmt"] = "0"
    live = gap.fetch_live_gap(QUERY, detail_codes=["4217210101"], window=WINDOW, client=FakeClient({"4217210101": [cancel]}))

    merged = gap.merge_live_gap(indexed, live)

    assert [c.source_record_id for c in merged.candidates] == ["delivery:R2|change:00|line:1"]


class PagedClient:
    """Serves fixed pages per detail code with an explicit totalCount (B-01 boundary cases)."""

    def __init__(self, pages: dict[str, list[list[dict[str, Any]]]], total: dict[str, int]) -> None:
        self.pages = pages
        self.total = total
        self.calls: list[dict[str, Any]] = []

    def get_json(self, base_url: str, endpoint: str, **params: Any) -> dict[str, Any]:
        self.calls.append(params)
        code = params["dtilPrdctClsfcNo"]
        code_pages = self.pages.get(code, [])
        index = params["pageNo"] - 1
        items = code_pages[index] if index < len(code_pages) else []
        return {
            "response": {
                "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
                "body": {
                    "items": items,
                    "totalCount": self.total.get(code, len(items)),
                    "pageNo": params["pageNo"],
                    "numOfRows": 999,
                },
            }
        }


def _full_page(prefix: str) -> list[dict[str, Any]]:
    return [_item(f"{prefix}{n}") for n in range(gap.LIVE_PAGE_SIZE)]


def test_empty_page_below_total_count_is_partial_not_zero() -> None:
    client = PagedClient({"4217210101": [[]]}, {"4217210101": 10_000})

    result = gap.fetch_live_gap(
        QUERY, detail_codes=("4217210101",), window=WINDOW, client=client, request_budget=1
    )

    assert result.status == gap.LIVE_PARTIAL_STATUS
    assert result.status in gap.LIVE_INCOMPLETE_STATUSES
    assert result.candidates == ()


def test_budget_spent_before_the_last_page_and_code_is_partial() -> None:
    client = PagedClient(
        {"4217210101": [_full_page("A")], "4217210102": [[_item("B1")]]},
        {"4217210101": 1_500, "4217210102": 1},
    )

    result = gap.fetch_live_gap(
        QUERY,
        detail_codes=("4217210101", "4217210102"),
        window=WINDOW,
        client=client,
        request_budget=1,
    )

    assert [call["dtilPrdctClsfcNo"] for call in client.calls] == ["4217210101"]
    assert result.status == gap.LIVE_PARTIAL_STATUS
    assert result.candidates == ()
    assert result.rows_seen == gap.LIVE_PAGE_SIZE


def test_partial_live_rows_are_not_merged_into_the_indexed_result() -> None:
    indexed = TrackBQuoteComparison("success_0", (), 0)
    partial = gap.TrackBLiveGapFill(gap.LIVE_PARTIAL_STATUS, "실시간 조회를 끝까지 하지 못함")

    assert gap.merge_live_gap(indexed, partial) is indexed


def test_every_page_read_is_still_success() -> None:
    client = PagedClient(
        {"4217210101": [_full_page("A"), [_item("A-last")]]},
        {"4217210101": gap.LIVE_PAGE_SIZE + 1},
    )

    result = gap.fetch_live_gap(
        QUERY, detail_codes=("4217210101",), window=WINDOW, client=client, request_budget=6
    )

    assert len(client.calls) == 2
    assert result.status == "success"


def test_live_rows_say_they_are_not_archived_with_time_range_and_fingerprint() -> None:
    """Review B-05: a live row is a session observation; 원문 위치 never reads as a kept page."""

    from purchase_price.services import g2b_delivery_record as record
    from purchase_price.ui.track_b_transactions import _transaction_row

    client = FakeClient({"4217210101": [_item("R1")]})
    result = gap.fetch_live_gap(QUERY, detail_codes=["4217210101"], window=WINDOW, client=client)
    (candidate,) = result.candidates

    key = candidate.raw_object_key
    assert key.startswith("live:4217210101:2026-09-19:2026-10-05:1:")
    assert key.count(":") == 6 and not key.endswith(".json.gz")

    text = record.describe_raw_key(key)
    assert text.startswith("보관 안 됨 · 실시간 조회 20")
    assert "세부품명번호 4217210101 2026-09-19~2026-10-05 1쪽" in text
    assert "응답 확인값 " in text

    row = _transaction_row(candidate, comparison_level="같은 제품")
    assert row["원문근거키"] == text
    # The trade dialog sees no archived page and says so instead of reading R2.
    ref = record.parse_record_ref(row["원천기록"], row["원문근거키"])
    assert ref is not None and ref.payload_hash is None
    assert record.load_delivery_record(ref).status == "not_archived"


def test_archived_and_older_live_keys_are_described_plainly() -> None:
    from purchase_price.services.g2b_delivery_record import describe_raw_key

    archived = "raw/g2b/track-b/" + "a" * 64 + ".json.gz"
    assert describe_raw_key(archived) == archived
    assert describe_raw_key("live:4217210101:2026-09-19:2026-10-05:1") == "보관 안 됨 · 실시간 조회(수집 전)"
    assert describe_raw_key(None) == ""
