from pathlib import Path

PAGE = Path("pages/15_전체구매검토_UAT.py")


def test_real_purchase_review_uat_page_is_deidentified_and_uses_shared_summary_contract() -> None:
    text = PAGE.read_text(encoding="utf-8")

    assert "전체 구매검토 UAT" in text
    assert "summarize_real_uat" in text
    assert "normalize_entry_rows" in text
    assert "render_review_csv" in text
    assert "검토완료" in text
    assert "Critical FP" in text
    assert "직접가격 확보율" in text
    assert "근거 추적 성공률" in text
    assert "평균 시간절감" in text
    assert "비식별 UAT CSV" in text
    assert "요약 JSON" in text
    assert "요약 Markdown" in text


def test_real_purchase_review_uat_page_does_not_collect_raw_quote_identity_or_price() -> None:
    text = PAGE.read_text(encoding="utf-8")

    assert "견적 원문, 업체명, 제품명, 모델명, 단가, 병원 내부정보는 입력하지 않습니다." in text
    assert "실제 파일명 대신 REAL-001" in text
    assert "실제 단가·내부 구매정보가 포함되지 않습니다" in text
    assert "file_uploader" not in text
