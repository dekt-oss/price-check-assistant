from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from purchase_price.models import Base
from purchase_price.services.g2b_track_b_normalization import TrackBRawPage
from purchase_price.services.track_b_db_quote_comparison import ingest_track_b_page
from purchase_price.services.track_b_supplier_summary import supplier_trade_summary
from purchase_price.ui import search_overviews as ov


def _rec(product, model, permit, company="(주)메디아나", classification="A12345.01", grade="3"):
    return SimpleNamespace(
        product_name=product,
        model_name=model,
        permit_number=permit,
        registered_company=company,
        classification_no=classification,
        grade=grade,
    )


def _link(model, permit, count, price="", latest="", company="(주)메디아나"):
    return {
        "유형": "허가",
        "식약처 품목번호": permit,
        "모델": model,
        "현재 모델": "",
        "품목 책임주체": company,
        "나라장터 직접거래": count,
        "나라장터 가격범위": price if count else "직접 동일성 확인 거래 0건",
        "최근거래": latest,
        "실제 조달 공급업체": "납품사" if count else "",
    }


RECORDS = [
    _rec("자동심장충격기", "A16-DS", "제허 19-527 호"),
    _rec("자동심장충격기", "A16-GF", "제허 20-49 호"),
    _rec("자동심장충격기", "A16-OS", "제허 20-49 호"),
    _rec("환자감시장치", "M50", "제허 10-1 호"),
]
LINKS = [
    _link("A16-DS", "제허 19-527 호", 92, "458,700 ~ 1,980,000원", "2026-10-01"),
    _link("A16-GF", "제허 20-49 호", 25, "1,800,000 ~ 1,980,000원", "2026-09-29"),
    _link("A16-OS", "제허 20-49 호", 0),
    _link("M50", "제허 10-1 호", 0),
]


def test_company_product_rows_group_by_item_busiest_first() -> None:
    rows = ov.company_product_rows(RECORDS, LINKS)

    assert [row["품목"] for row in rows] == ["자동심장충격기", "환자감시장치"]
    first = rows[0]
    assert first["등록 모델"] == 3
    assert first["식약처 품목번호"] == 2
    assert first["조달가격 있는 모델"] == 2
    assert first["나라장터 거래"] == "117건"
    assert first["가격범위"] == "458,700 ~ 1,980,000원"
    assert first["최근거래"] == "2026-10-01"
    assert first["대표 모델"] == "A16-DS / A16-GF / A16-OS"


def test_company_model_rows_list_each_model_once_priced_first() -> None:
    rows = ov.company_model_rows(RECORDS + [RECORDS[0]], LINKS)

    assert [row["모델"] for row in rows] == ["A16-DS", "A16-GF", "A16-OS", "M50"]
    assert rows[0]["식약처 품목번호"] == "[허가] 제허 19-527 호"
    assert rows[0]["나라장터 거래"] == "92건"
    assert rows[2]["가격범위"] == ""


def test_classification_rows_count_companies_models_and_items() -> None:
    records = [
        _rec("자동심장충격기", "A", "제허 1 호", company="가", classification="A1", grade="3"),
        _rec("자동심장충격기", "B", "제허 2 호", company="나", classification="A1", grade="3"),
        _rec("자동심장충격기", "C", "제허 3 호", company="나", classification="A2", grade="2"),
    ]
    rows = ov.classification_rows(records)

    assert rows[0] == {
        "분류번호": "A1",
        "등급": "3",
        "품목": "자동심장충격기",
        "품목 책임주체": 2,
        "등록 모델": 2,
        "식약처 품목번호": 2,
    }


def test_supplier_row_is_labelled_as_name_match_only() -> None:
    row = ov.supplier_summary_row(
        {"trade_count": 238, "matched_names": ["(주)메디아나"], "model_count": 9, "institution_count": 120,
         "latest": "2026-10-01", "top_models": ["HeartOn A16-DS 92건"]},
        "(주)메디아나",
    )
    assert row["업체 동일성"] == "명칭 일치 · 사업자번호 미확인"
    assert ov.supplier_summary_row({"trade_count": 0}, "x") is None


def _page(items):
    return TrackBRawPage(
        payload={
            "schema": "g2b-track-b-page-v1",
            "operation": "getSpcifyPrdlstPrcureInfoList",
            "request": {
                "detail_code": "4217210101",
                "begin_date": "2025-09-12",
                "end_date": "2026-09-11",
                "page_no": 1,
                "page_size": 999,
                "final_change_order_filter": "OMITTED",
            },
            "response": {"items": items},
        },
        raw_object_key="raw/v1/getSpcifyPrdlstPrcureInfoList-page/test.json.gz",
        raw_payload_sha256="a" * 64,
    )


def _item(n, supplier, *, change="00", qty="1"):
    return {
        "cntrctDlvrReqNo": f"R{n}",
        "cntrctDlvrReqChgOrd": change,
        "prdctSno": "1",
        "dtilPrdctClsfcNo": "4217210101",
        "prdctIdntNoNm": "자동심장충격기, 메디아나, A16-DS, 보관함",
        "prdctUprc": "1980000",
        "prdctQty": qty,
        "prdctAmt": str(1980000 * int(qty)),
        "cntrctDlvrReqDate": "20260901",
        "corpNm": supplier,
        "dminsttNm": f"기관{n}",
    }


def test_supplier_summary_matches_legal_form_variants_and_skips_cancelled(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'i.sqlite'}")
    Base.metadata.create_all(engine)
    session = Session(bind=engine)
    ingest_track_b_page(
        session,
        _page(
            [
                _item(1, "(주)메디아나"),
                _item(2, "주식회사 메디아나"),
                _item(3, "메디아나헬스"),  # different company, same prefix
                _item(4, "(주)메디아나"),
            ]
        ),
    )
    ingest_track_b_page(session, _page([_item(4, "(주)메디아나", change="01", qty="0")]))  # cancelled
    session.commit()

    summary = supplier_trade_summary(session, "(주)메디아나")

    assert summary["trade_count"] == 2
    assert summary["matched_names"] == ["(주)메디아나", "주식회사 메디아나"]
    assert summary["institution_count"] == 2
    assert supplier_trade_summary(None, "메디아나")["status"] == "not_applicable"
    session.close()
    engine.dispose()


def test_dashboard_routes_company_and_product_matches_to_overviews() -> None:
    source = Path("pages/1_대시보드.py").read_text(encoding="utf-8")

    route = source.index('indexed_identity.match_type in {"company", "product"}')
    # The model-ambiguity picker inside _execute_search (the permit picker has its own builder).
    search = source.index("def _execute_search(")
    assert route < source.index('"route": "candidate_selection"', search)
    assert (
        "return _build_overview_state(\n            raw_search, indexed_identity, snapshot_runtime, "
        "prefer_traded_company=prefer_traded_company" in source
    )
    assert 'elif search_state.get("route") in overview_ui.OVERVIEW_ROUTES:' in source
    # A category word opens the 품목 picker (2026-10-09 acceptance).
    assert 'elif search_state.get("route") == overview_ui.CATEGORY_ROUTE:' in source
    assert "overview_ui.looks_like_category_word(raw_search)" in source
    assert "lookup_model_summaries(queries, limit_per_model=500)" in source
    assert 'id="purchase-workspace-runtime-v16"' in source


def test_company_name_variants_only_add_legal_forms() -> None:
    variants = ov.company_name_variants("메디아나")
    assert "(주)메디아나" in variants and "주식회사 메디아나" in variants and "메디아나 유한회사" in variants
    assert ov.company_name_variants("(주)메디아나") == []
    assert ov.company_name_variants("주식회사 메디아나") == []
    assert ov.company_name_variants("A") == []


def test_category_words_are_korean_words_without_digits() -> None:
    assert ov.looks_like_category_word("심장충격기")
    assert ov.looks_like_category_word("환자 감시장치")
    assert not ov.looks_like_category_word("zzqq없는모델123")
    assert not ov.looks_like_category_word("HeartOn A16-DS")
    assert not ov.looks_like_category_word("M40")
    assert not ov.looks_like_category_word("가")


def test_category_rows_put_common_purchase_items_first() -> None:
    rows = ov.category_rows(
        [
            {"product_name": "이식형 심장충격기용 전극", "models": 180, "companies": 5},
            {"product_name": "저출력 심장 충격기", "models": 134, "companies": 15},
            {"product_name": "", "models": 1, "companies": 1},
        ]
    )
    assert [row["식약처 품목명"] for row in rows] == ["저출력 심장 충격기", "이식형 심장충격기용 전극"]
    assert rows[0]["업체 수"] == 15


def test_company_with_trades_is_preferred_only_when_the_exact_name_has_none() -> None:
    candidates = [
        {"name": "(주)메디아나", "models": 108, "priced_models": 15},
        {"name": "메디아나(주)", "priced_models": 0},
    ]
    assert ov.pick_traded_company(0, candidates)["name"] == "(주)메디아나"
    assert ov.pick_traded_company(3, candidates) is None
    assert ov.pick_traded_company(0, [{"name": "x", "priced_models": 0}]) is None


def test_dashboard_pins_the_clicked_registration_from_an_overview() -> None:
    source = Path("pages/1_대시보드.py").read_text(encoding="utf-8")
    assert "result_summary_ui.overview_model_keys(crosslinks)" in source
    assert 'st.query_params["identity"] = identity_token' in source
    assert 'prefer_traded_company=str(st.query_params.get("exact") or "") != "1"' in source
    assert "_open_model_from_overview(str(similar[\"name\"]), exact_company=True)" in source
