# HANDOFF — Phase P2a (검색 시간 측정·단계 표시)

## 1. 기준 커밋과 작업 브랜치
- `578063e`(#346 머지) · 브랜치 `claude/ux-v11-price` · 워크트리 `.worktrees/ux-v11-price`

## 2. Phase 목적
검색이 어디서 오래 걸리는지 운영에서 단계별로 재고, 기다리는 동안 지금 무엇을 하는지 보여 준다. 구조 개선(P2b)은 측정 결과를 본 뒤 정한다.

## 3. 완료한 요구사항
- 검색 상자 문구가 단계마다 바뀐다(검색이 실행되는 다섯 곳 모두)
- 숨김 마커 `purchase-search-timings-v2`(단계 전체 + 시작 대기 + 차가운 상태 여부), `purchase-render-timings-v1`(결론 카드까지 그리기)
- 측정 도구 `purchase_price.scripts.measure_price_search_timings`와 워크플로 **Price Search Timings**(`.github/workflows/track-b-search-timings.yml`, 하루 3회 + 수동). 표본은 R2 `state/v1/perf/price-search-timings.json`
- 문서 `docs/performance/UX_V11_PRICE_BASELINE.md`(측정 정의, P2b 판단 기준)

## 4. 변경 파일
`pages/1_대시보드.py`, `src/purchase_price/scripts/measure_price_search_timings.py`, `.github/workflows/track-b-search-timings.yml`, `tests/test_price_search_timings.py`, `docs/performance/UX_V11_PRICE_BASELINE.md`

## 5. 데이터 계약
`_execute_search(..., progress=None)`: 단계 이름(identity, track_b, category_market, track_b_live, safety)을 넘기는 콜백. R2 상태 객체 `{"version": 1, "samples": [...]}`.

## 6. 실행한 테스트
`pytest -q tests/test_price_search_timings.py` 등 25개 통과(PR #346). 로컬 앱에서 단계 문구와 마커 값 확인.

## 7. 미검증
- 운영 표본(머지 직후 워크플로 수동 실행 결과는 PR 다음 보고에 기록).
- GitHub 정기 실행이 실제로 하루 3번 도는지(이 저장소에서 정기 실행이 늦거나 빠진 전례가 있음).

## 8. 알려진 위험·관찰
- 로컬: 방금 내려받은 인덱스에서 HeartOn A16-DS 같은 제품 거래 조회가 23초.
- 운영: P1 배포 직후 첫 세션의 검색이 4분 넘게 끝나지 않았고, 같은 시각 새 세션은 30초 안에 결과가 떴다. 재시작 직후 인덱스 준비와 첫 세션 검색이 겹친 것으로 보이며 P2b의 첫 조사 대상이다.

## 9. 다음 Phase 시작 지점 (P2b)
1. 1주일 표본으로 `UX_V11_PRICE_BASELINE.md` 4장을 채운다(`python -m purchase_price.scripts.measure_price_search_timings --r2 --summary`는 새 표본을 더한 뒤 요약하므로, 요약만 보려면 R2 객체를 읽어 `summary_markdown`에 넘긴다).
2. 5장 기준으로 범위를 정한다. 따뜻한 상태에서 `track_b`가 지배적이면 모델별 요약 파일 사전 생성.
3. 재시작 직후 첫 세션 대기(8장)를 재현하고 원인(압축 해제 중 조회 대기, 잠금)을 확인한다.

## 10. 재현 명령
```bash
pip install "playwright>=1.55,<2" && python -m playwright install chromium
PYTHONPATH=src python -m purchase_price.scripts.measure_price_search_timings --url http://localhost:8505/ --output .local/timings.json --summary
```

## 11. 캡처
검색 중 문구 "4/4 회수·판매중지 확인 중 · 식약처"(로컬).

## 12. 공통 파일 변경 요청
없음.
