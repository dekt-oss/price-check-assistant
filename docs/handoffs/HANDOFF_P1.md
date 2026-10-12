# HANDOFF — Phase P1 (거래가 비교 결과 카드)

## 1. 기준 커밋과 작업 브랜치
- 시작 `0656191`(P0 머지) · 브랜치 `claude/ux-v11-price` · 워크트리 `.worktrees/ux-v11-price`
- 보조 브랜치(합쳐짐): `claude/ux-v11-p1-excel`(a7c049b), `claude/ux-v11-p1-quote-review`(06e87b9)

## 2. Phase 목적
상세 표를 읽기 전에 견적가가 같은 제품 거래의 어디쯤인지, 그 근거가 얼마나 단단한지를 결론 카드에서 읽게 한다. 모든 숫자는 P0 계약(`services/price_metrics.py`)에서 나온다.

## 3. 완료한 요구사항
- 결론 카드 위쪽에 비교 결과 상태(거래 범위 안 (조건 미확인) / 확인 필요 / 비교 근거 부족 / 동일 제품 확인 필요)와 근거 수준(높음·보통·제한적 + 이유)
  - 견적가를 넣지 않았고 거래가 3건 이상이면 상태는 숨기고 근거 수준만 보인다
- 결론 문장에 원 단위 차이 `(+120,000원)` 추가
- 기준 줄의 제외 건수를 계약 기준으로: `(제외 2건: 다른 단위 2(set))`, `(제외 2건: 입력 오류 의심 2)`
- 최근 거래 원문 3건 링크(나라장터 원문)
- 같은 제품 가격 계산 거래가 1~2건이면 회색 점선 상자로 제품군 참고 시세 한 줄(0건이면 기존처럼 제품군 시장이 본문)
- 자료 기준일이 3일 넘게 지났고 실시간 확인이 없으면 자료 기준 칩이 노란색
- 견적 검토 페이지가 같은 계약으로 계산(기준 단위 선택이 결과 화면과 같아짐), 판정 문구를 계약 문구로
- Excel 시장조사표 요약 시트에 계약 지표, A_B 시트에 `가격 계산 포함` 열(스키마 v2)
- 런타임 마커: `PRICE_METRICS_V1`, `RESULT_LAYOUT_COMPARISON_V1`, `QUOTE_REVIEW_PRICE_CONTRACT_V1`, `MARKET_SURVEY_PRICE_CONTRACT_V1` (대시보드 재적재 목록에 추가), 배포 마커 `purchase-workspace-runtime-v22` 추가(v21 유지)

## 4. 변경 파일
`pages/1_대시보드.py`, `src/purchase_price/ui/result_layout.py`, `src/purchase_price/ui/quote_review_layout.py`, `src/purchase_price/services/market_survey_export.py`, `docs/metrics/price.md`, 테스트 `tests/test_result_comparison_card.py`(신규), `tests/test_result_layout.py`, `tests/test_quote_review_layout.py`, `tests/test_market_survey_export.py`, `tests/test_price_metrics.py`. 모두 Track P 허용목록 안.

## 5. 데이터 계약 변경
- `build_market_survey_workbook(..., price_result=None, direct_row_basis=None)`, `MARKET_SURVEY_EXPORT_SCHEMA = "workspace-v3-market-survey-xlsx-v2"`
- `quote_review_layout.VERDICT_*` 값이 계약 문구로 바뀜(상수 이름은 그대로). `TradeStats.summary` 추가
- `result_layout.lead_view(..., excluded_text=None)`, `lead_row_html(..., status_html="", after_price_html="")`, `basis_chip(..., stale=False)`

## 6. 실행한 테스트
PR 본문에 명령과 결과를 적는다.

## 7. 미검증
- 운영 배포 뒤 화면(머지 후 확인 예정).
- 근거 수준 기준값에 대한 구매팀 반응.

## 8. 알려진 위험
- 견적 검토는 기간 안 단위가 아니라 전체 기간 기준 단위를 쓰게 되어, 단위를 섞은 일부 모델의 판정이 바뀔 수 있다(의도된 정렬).
- 운영 스모크는 아직 v21을 본다. v22 확인은 수동.

## 9. 다음 Phase 시작 지점 (P2a)
`pages/1_대시보드.py`의 `search_timings` 단계(identity, track_b, category_market, track_b_live, mfds, safety)를 작업지시서 P2a의 단계(앱 진입·인덱스 준비·identity·동일 모델 요약·결과 카드·제품군·선택형 외부 조회)로 나누고, 숨김 마커 `purchase-search-timings-v1`에 차가운/따뜻한 상태를 기록한다.

## 10. 재현 명령
```bash
cd .worktrees/ux-v11-price
PYTHONPATH="$PWD/src" ../../.venv/Scripts/python.exe -m pytest -q tests/test_result_comparison_card.py tests/test_price_metrics.py tests/test_result_layout.py tests/test_quote_review_layout.py tests/test_market_survey_export.py
```

## 11. 캡처
PR 본문에 첨부.

## 12. 공통 파일 변경 요청 (통합 I0)
- `scripts/production_unified_search_smoke.py`와 `tests/test_production_runtime_research_safety.py`, `tests/test_production_unified_search_smoke_contract.py`, `tests/test_simple_result_ui_contract.py`의 배포 마커를 v21에서 v22로 올리기(운영 스모크가 새 배포를 구분하도록).
