# HANDOFF — Phase P0 (가격 지표 계약)

## 1. 기준 커밋과 작업 브랜치
- BASE_SHA `ecb888b` · 브랜치 시작 `020224c` · 브랜치 `claude/ux-v11-price` · 워크트리 `.worktrees/ux-v11-price`

## 2. Phase 목적
모든 같은 제품 가격 숫자의 기준을 하나로 정하고, 지금 화면들이 그 기준과 어디서 다른지 기록한다. 화면은 바꾸지 않는다.

## 3. 완료한 요구사항
- 현재 가격 계산 경로 8곳 인벤토리와 차이 8건: `docs/metrics/price.md` 6장
- 지표 정의(계산 대상·제외 규칙·지표·견적 비교·근거 수준): `docs/metrics/price.md` 1~4장
- 계약 코드: `src/purchase_price/services/price_metrics.py` (`PriceTrade`, `summarize_same_model`, `compare_quote`, `evidence_level`, `build_price_result` → `PriceResult`)
- 골든 fixture 6종: `tests/fixtures/price/` (요구 5종 + 기간별 기준 단위가 바뀌는 사례 1종)
- 데이터 감사: 로컬 인덱스 사본(2026-10-10)으로 표본 크기·단위 혼합·구간 밀도·기관명 변형 실측, `docs/metrics/price.md` 5장
- 미확정 항목 6개에 대한 P0 결론: `docs/metrics/price.md` 7장

## 4. 변경 파일
- 추가: `src/purchase_price/services/price_metrics.py`, `tests/test_price_metrics.py`, `tests/fixtures/price/*.json`(6), `docs/metrics/price.md`, `docs/handoffs/HANDOFF_P0.md`
- 수정: 없음 (허용목록 안)

## 5. 데이터 계약
`PriceResult(summary: SameModelSummary, comparison: QuoteComparison, evidence: EvidenceLevel, period_label, data_as_of, data_as_of_stale, show_category_in_conclusion)`. 입력은 `PriceTrade.from_candidate(TrackBQuoteCandidate)`로 만든다. 런타임 마커 `PRICE_METRICS_V1`.

## 6. 실행한 테스트
- `pytest -q tests/test_price_metrics.py` → 42 passed. 결과 화면(`build_purchase_workspace_stats` + 단위 분리)과 6종 모두 가운데 값·최저·최고·건수·기관 수·업체 수·견적 차이가 같고, 견적 검토와는 5종이 같다.
- 전체 테스트·ruff 결과는 PR 본문에 적는다.

## 7. 미검증
- 운영 인덱스 최신본에서의 감사 수치(로컬 사본은 2026-10-10 수집분).
- 비의료 대량 품목(노트북 등)에서 조회 상한 5,000행이 숫자를 자르는지.

## 8. 알려진 위험
- 결과 화면과 견적 검토가 기간마다 다른 기준 단위를 고를 수 있다(fixture `unit_changes_by_period`). P1에서 견적 검토를 계약에 맞추면 일부 견적 판정이 바뀐다.
- 근거 수준 기준값은 실측 분포로 정했지만 사용자 검증 전이다(높음 89 · 보통 890 · 제한적 208, 최근 3년 3건 이상 모델 기준 근사).

## 9. 다음 Phase 시작 지점 (P1)
1. `pages/1_대시보드.py` `_render_search_result`에서 `build_purchase_workspace_stats` 대신 `price_metrics.build_price_result`를 만들고 `result_summary.build_conclusion`·`result_layout`이 그것을 읽게 한다.
2. 비교 결과 상태 4개와 근거 수준을 결론 카드에 표시한다. 제품군 참고 시세는 `show_category_in_conclusion`일 때만 결론에 올린다.
3. 견적 검토(`quote_review_layout.comparable_trade_stats`)를 계약으로 바꾸고 `test_known_gap_quote_review_picks_the_period_unit`을 지운다.
4. Excel 요약 시트에 가격 계산 건수·가운데 값·기준 단위를 넣는다.

## 10. 재현 명령
```bash
cd .worktrees/ux-v11-price
PYTHONPATH="$PWD/src" ../../.venv/Scripts/python.exe -m pytest -q tests/test_price_metrics.py
```
감사 스크립트는 저장소에 넣지 않았다(로컬 사본 경로 의존). 수치는 `docs/metrics/price.md` 5장.

## 11. 캡처·결과 예시
화면 변경 없음.

## 12. 공통 파일 변경 요청
없음.
