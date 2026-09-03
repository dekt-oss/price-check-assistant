from purchase_price.scripts.capture_g2b_ground_truth_candidates import select_identity_sample


def _row(record_id: str, title: str, day: str) -> dict[str, str]:
    return {"source_record_id": record_id, "candidate_title": title, "transaction_date": day}


def test_identity_sample_keeps_one_row_per_title_with_transaction_count() -> None:
    same = "노트북컴퓨터, 삼성전자, (VN)NT750XHD-K7P62, Intel Core Ultra 7 255U(2.0GHz)"
    other = "인공호흡기, 조선기기, CSI-2000, 운반형"
    ranked = [
        (2, "2026-07-20", _row("R-3", same, "2026-07-20")),
        (2, "2026-07-16", _row("R-2", same, "2026-07-16")),
        (1, "2026-07-18", _row("R-1", same.replace("-", " "), "2026-07-18")),
        (0, "2026-07-15", _row("R-0", other, "2026-07-15")),
    ]

    selected = select_identity_sample(ranked, max_rows=10)

    assert [row["source_record_id"] for row in selected] == ["R-0", "R-1"]
    assert selected[0]["transaction_count"] == "1"
    # punctuation-only variants of the same title are one identity; best-ranked row is kept
    assert selected[1]["transaction_count"] == "3"


def test_identity_sample_respects_max_rows_after_dedupe() -> None:
    ranked = [
        (0, "2026-07-15", _row(f"R-{i}", f"품목 {i}", "2026-07-15")) for i in range(5)
    ]

    assert len(select_identity_sample(ranked, max_rows=3)) == 3
