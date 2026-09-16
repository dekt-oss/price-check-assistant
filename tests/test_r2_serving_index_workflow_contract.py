from pathlib import Path


def test_r2_serving_index_workflow_runs_after_daily_backfill() -> None:
    text = Path(".github/workflows/track-b-r2-serving-index.yml").read_text()

    assert "push:" in text
    assert "branches:" in text
    assert "- main" in text
    assert '"Track B Daily Backfill"' in text
    assert "github.event_name == 'push'" in text
    assert "sync_g2b_track_b_r2_index" in text
    assert "R2_ACCOUNT_ID: ${{ secrets.R2_ACCOUNT_ID }}" in text
    assert "DATABASE_URL" not in text
    assert "group: track-b-r2-pipeline" in text
    assert '"psycopg[binary]>=3.2,<4"' in text
    assert '"httpx>=0.27,<1"' in text
    assert '"tenacity>=9,<10"' in text


def test_home_is_unified_search_and_upload_entrypoint() -> None:
    text = Path("pages/1_대시보드.py").read_text()

    assert "무엇을 조사할까요?" in text
    assert "상세 검색조건" in text
    assert "home_quote_upload" in text
    assert 'st.switch_page("pages/2_견적_검토.py")' in text
    assert "lookup_track_b_quote_from_r2" in text
    assert "model_probe_input" in text
    assert "model_name=raw_search" in text
    assert "모델 기준 결과를 우선 표시" in text
