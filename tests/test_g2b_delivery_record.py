from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from purchase_price.services import g2b_delivery_record as record
from purchase_price.ui import result_summary as rs

HASH = "cb171fb45794f65672a208535b6e8adc2283a60b578c87d2e745d6d873584e9f"
KEY = f"raw/v1/getSpcifyPrdlstPrcureInfoList-page/cb/17/{HASH}.json.gz"
LINE = {
    "cntrctDlvrReqNm": "취약지 응급의료기관 장비지원사업",
    "cntrctDlvrReqNo": "R26TA02247191",
    "cntrctDlvrReqChgOrd": "00",
    "cntrctDlvrReqDate": "20260928",
    "dminsttNm": "의료법인 성수의료재단(비에스종합병원)",
    "corpNm": "세명에이스메디칼",
    "prdctIdntNoNm": "환자감시장치, 메디아나, M40",
    "prdctIdntNo": "24522296",
    "prdctSno": "2",
    "prdctUprc": "36513000",
    "prdctQty": "2",
    "prdctUnit": "set",
    "prdctAmt": "73026000",
    "cntrctDivNm": "총액계약",
    "cntrctMthdNm": "일반경쟁",
    "prcrmntDivNm": "자체조달",
    "dlvrTmlmtDate": "20261023",
    "masYn": "N",
}
PAGE = {"response": {"body": {"items": [{**LINE, "prdctSno": "1", "prdctUprc": "4400000"}, LINE]}}}


def _ref(line: str = "2", key: str = KEY) -> record.DeliveryRecordRef:
    parsed = record.parse_record_ref(f"delivery:R26TA02247191|change:00|line:{line}", key)
    assert parsed is not None
    return parsed


def test_parse_record_ref_and_label() -> None:
    ref = _ref()
    assert ref.delivery_number == "R26TA02247191"
    assert ref.payload_hash == HASH
    assert ref.label == "R26TA02247191 · 2번 물품"
    assert record.parse_record_ref("live:abc", KEY) is None
    changed = record.parse_record_ref("delivery:R1|change:01|line:3", KEY)
    assert changed is not None and changed.label == "R1 · 3번 물품 · 변경 01"


def test_load_finds_the_exact_line_and_formats_plain_labels() -> None:
    seen: list[tuple[str, str]] = []

    def reader(key: str, payload_hash: str) -> object:
        seen.append((key, payload_hash))
        return PAGE

    lookup = record.load_delivery_record(_ref(), read_payload=reader)

    assert seen == [(KEY, HASH)]
    assert lookup.status == "found"
    fields = dict(lookup.fields)
    assert fields["사업명"] == "취약지 응급의료기관 장비지원사업"
    assert fields["단가"] == "36,513,000원"
    assert fields["수량"] == "2"
    assert fields["단위"] == "set"
    assert fields["금액"] == "73,026,000원"
    assert fields["계약 구분"] == "총액계약"
    assert fields["납품 기한"] == "2026-10-23"
    assert fields["다수공급자계약(MAS)"] == "아니요"
    assert list(fields)[:5] == ["사업명", "단가", "수량", "단위", "금액"]


def test_live_lines_without_an_archived_page_are_not_read() -> None:
    def reader(key: str, payload_hash: str) -> object:  # pragma: no cover - must not be called
        raise AssertionError("live rows have no archived page")

    lookup = record.load_delivery_record(_ref(key="live:4218190401:2026-10-01:2026-10-07:1"), read_payload=reader)
    assert lookup.status == "not_archived"


def test_missing_line_and_read_failure_are_reported_not_raised() -> None:
    assert record.load_delivery_record(_ref(line="9"), read_payload=lambda k, h: PAGE).status == "not_found"

    def broken(key: str, payload_hash: str) -> object:
        raise TimeoutError("r2 slow")

    failed = record.load_delivery_record(_ref(), read_payload=broken)
    assert failed.status == "failure"
    assert failed.error_type == "TimeoutError"


def test_price_outliers_are_three_times_from_the_median_farthest_first() -> None:
    rows = [
        {"가격": "4,400,000원", "원천기록": "a"},
        {"가격": "36,513,000원", "총액": "73,026,000원", "수량": "2", "단위": "set", "거래조건": "총액계약 · 납품장소도", "구매처": "비에스종합병원", "거래일": "2026-09-28", "원천기록": "b"},
        {"가격": "1,000,000원", "원천기록": "c"},
        {"가격": "미확인", "원천기록": "d"},
    ]
    median = Decimal("4400000")
    outliers = rs.price_outlier_rows(rows, median)
    assert [row["원천기록"] for row in outliers] == ["b", "c"]
    line = rs.outlier_line(outliers[0], median, "대")
    assert line.startswith("73,026,000원 ÷ 2 set = 1 set당 36,513,000원 · 1대당 중앙값의 8.3배 높음 · 총액계약")
    assert rs.price_outlier_rows(rows, None) == []


def test_dashboard_wires_the_record_panel_and_reloads_new_helpers() -> None:
    source = Path("pages/1_대시보드.py").read_text(encoding="utf-8")
    assert "result_summary_ui.price_outlier_rows(direct_rows, median_price)" in source
    assert "_render_delivery_record(" in source
    assert 'key=record_table_key' in source and 'on_select="rerun"' in source
    assert '(track_b_transactions_ui, "BUSINESS_NAME_COLUMN")' in source
    assert "G2B_SHOPPING_DATASET_URL" not in source
    assert 'link_col.link_button("나라장터에서 이 거래 보기", ref.g2b_url' in source
    assert 'st.column_config.LinkColumn("나라장터", display_text="열기")' in source
    assert '("purchase_price.services.g2b_delivery_record", "G2B_LINK_V1")' in source
    assert '("purchase_price.ui.result_summary", "BUSINESS_NAME_V1")' in source
    assert record.G2B_LINK_V1 is True


def test_g2b_links_open_the_integrated_search_on_the_number() -> None:
    ref = _ref()
    assert ref.g2b_url == "https://www.g2b.go.kr/link/FIUA009_01/single/?searchKeyword=R26TA02247191"
    assert record.g2b_url_for_source_record("delivery:R26TB02199340|change:00|line:2") == (
        "https://www.g2b.go.kr/link/FIUA009_01/single/?searchKeyword=R26TB02199340"
    )
    assert record.g2b_url_for_source_record("live:abc") is None
    row = rs.trade_table_rows([{"가격": "4,400,000원", "원천기록": "delivery:R26TB02199340|change:00|line:2"}])[0]
    assert row["나라장터"].endswith("searchKeyword=R26TB02199340")
    assert list(row)[5] == "나라장터"
