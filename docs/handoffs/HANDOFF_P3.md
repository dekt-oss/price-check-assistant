# HANDOFF — Phase P3 (기간별 가격 변동 · 제품군 시장 요약)

## 1. 기준 커밋과 작업 브랜치
- 시작 `578063e`(P2a 머지) · 브랜치 `claude/ux-v11-price` · 보조 브랜치 `claude/ux-v11-p3-category`(fea2f66, 합쳐짐)

## 2. Phase 목적
같은 모델 가격이 기간별로 어떻게 움직였는지를 거짓 추세 없이 보여 주고, 제품군에서 누가 많이 팔렸는지를 순위가 품질로 읽히지 않게 보여 준다.

## 3. 완료한 요구사항
**P3a 기간별 가격**
- 계약 `price_metrics.price_trend`: 월·분기·연 중 "3건 이상 구간이 2개 이상이고 거래가 있는 구간의 절반 이상"인 가장 촘촘한 단위. 어느 단위도 맞지 않으면 그래프를 그리지 않고 이유를 말한다
- 변동 문장은 가장 최근의 3건 이상 두 구간만 비교하고 건수를 함께 적는다. 진행 중인 구간이면 "(진행 중인 구간)"을 붙인다. 상승·하락·추세 같은 말은 쓰지 않는다
- 그래프(`ui/price_trend.py`): 구간마다 가운데 값 점 + 최저~최고 막대, 점을 선으로 잇지 않음, 건수 부족 구간은 회색, 견적가는 빨간 점선
- 같은 숫자를 표로: 월·분기면 "기간별 숫자로 보기" 펼침, 연이면 기존 연도별 표
- "얼마에 거래됐나"의 첫 탭 이름을 "기간별"로
- 그래프 생성이 실패해도 페이지는 계속 그린다(그래프만 빠짐)
**P3b 제품군 상위 모델**
- `category_market.top_models(market, by="trades"|"institutions")`: 기간 안 장비 구매 줄만, 모델 미기재 제외, 기관 수는 공백·괄호만 지운 이름으로 셈(유사 이름 병합 없음)
- 화면: "거래 건수가 많은 모델"·"납품 기관이 많은 모델" 각 5개, 검색 모델 ▶ 표시, 5위 밖이면 "▶ 검색한 모델" 한 줄. "많이 거래된 순서일 뿐 품질이나 권장 순위가 아닙니다"
- 전체 모델 표는 "같은 품목 모델 전체 N개" 펼침 안으로(행 선택 동작 그대로)
- 제품군 거래가 6,000줄 상한에 걸리면 실제로 센 시작일과 "위 결론의 같은 제품 거래 수와 다를 수 있습니다"를 설명에 적는다

## 4. 변경 파일
`pages/1_대시보드.py`, `src/purchase_price/services/price_metrics.py`, `src/purchase_price/ui/price_trend.py`(신규), `src/purchase_price/services/category_market.py`, `src/purchase_price/ui/category_market.py`, `docs/metrics/price.md`, `docs/performance/UX_V11_PRICE_BASELINE.md`, 테스트 `tests/test_price_trend.py`(신규), `tests/test_category_top_models.py`(신규), `tests/test_simple_result_ui_contract.py`

## 5. 데이터 계약 변경
- `SameModelSummary.priced_trades`, `price_trend(summary, today) -> PriceTrend(granularity, buckets, change_from, change_to, change_percent)`
- `CategoryMarket` 쪽 `top_models`, `TopModel`, `searched_model_stats`
- 런타임 마커 `PRICE_TREND_V1`, `PRICE_TREND_UI_V1`, `CATEGORY_MARKET_TOP_MODELS_V1`(두 모듈) — 대시보드 재적재 목록에 추가

## 6. 실행한 테스트
PR 본문에 적는다.

## 7. 미검증
- 운영 화면(머지 뒤 확인).
- 제품군 그래프 비교선: 제품군은 대·세트·식을 한 단위로 묶어 같은 제품과 단위 규칙이 달라 작업지시서 규칙대로 같은 그래프에 넣지 않았다.

## 8. 알려진 위험
- 월 단위 비교는 표본이 적어(구간당 3건~) 변동 문장이 잦게 바뀔 수 있다. 문장은 건수를 함께 적어 판단을 돕는다.
- 제품군 6,000줄 상한(차이 9). 거래가 많은 품목은 기간 앞부분이 빠진다.

## 9. 다음 작업
- P2b: 첫 운영 표본에서 따뜻한 상태도 30초 안팎(같은 제품 거래 조회가 대부분). 모델별 요약 파일 사전 생성 후 결론 카드 먼저 그리기, 제품군 상한 재검토.
- I0 요청(공통 파일): 운영 스모크 배포 마커 v21 → v22 이상.

## 10. 재현 명령
```bash
cd .worktrees/ux-v11-price
PYTHONPATH="$PWD/src" ../../.venv/Scripts/python.exe -m pytest -q tests/test_price_trend.py tests/test_category_top_models.py tests/test_price_metrics.py
```

## 11. 캡처
로컬: PNB-704(월별 → 규칙 보강 뒤 분기별 예상), HeartOn A16-DS(월별, 상위 모델: 나눔테크 NT-381.B 720건 · 납품 기관 584곳 · 1,540,000원, 검색 모델 163건 줄).

## 12. 공통 파일 변경 요청
9장 두 번째 항목.
