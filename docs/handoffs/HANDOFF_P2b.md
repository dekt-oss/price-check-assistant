# HANDOFF — Phase P2b (검색 속도 구조 개선, 1차)

## 1. 기준 커밋과 작업 브랜치
- #348(같은 제품 조회 한 번에 읽기), #349(별칭 파일 캐시) 머지 · 브랜치 `claude/ux-v11-price`

## 2. Phase 목적
P2a 첫 운영 측정에서 따뜻한 상태도 거래가 많은 모델은 25~35초였다. 원인을 프로파일링으로 찾아, 화면 결과를 바꾸지 않는 범위에서 고친다. 작업지시서가 예로 든 "모델별 요약 파일 사전 생성"은 아래 원인 수정만으로 충분한지 재측정 뒤 정한다.

## 3. 완료한 요구사항
- 같은 제품 거래 조회: 행마다 SQL 4번 더 나가던 지연 로딩 제거, 품명별 판정 재사용(#348)
- 같은 품목 모델 집계: 판정마다 별칭 CSV 2개를 다시 열던 것을 파일별 캐시로(#349)
- 숨김 마커 v2에 `track_b_lookup`, `same_item_models`, `overview_probe` 단계 추가(측정 스크립트 포함)
- 측정 결과는 `docs/performance/UX_V11_PRICE_BASELINE.md` 6~8장

## 4. 변경 파일
`src/purchase_price/services/track_b_db_quote_comparison.py`, `src/purchase_price/services/product_matching.py`, `pages/1_대시보드.py`, `src/purchase_price/scripts/measure_price_search_timings.py`, 테스트 `tests/test_track_b_db_quote_comparison.py`, `tests/test_product_matching.py`, 문서

## 5. 데이터 계약
변경 없음(조회 결과 동일). 재적재 마커 `LOOKUP_NO_LAZY_LOADS_V1`, `ALIAS_REGISTRY_CACHE_V1`.

## 6. 실행한 테스트
각 PR 본문 참조. 로컬 전체 1,760 passed, 7 failed(Windows 전용 OCR).

## 7. 미검증
- 차가운 상태 앱 기동 구간(첫 표본 135초 중 약 108초)은 검색 바깥이라 아직 나누지 못함.

## 8. 알려진 위험
- 별칭 캐시는 60초마다 파일을 확인한다. 운영에서는 배포마다 앱이 재시작해 문제없다.

## 9. 다음 작업
- 1주일 표본 뒤 따뜻한 상태 중앙값을 보고 모델별 요약 파일 사전 생성 필요 여부 결정.
- 같은 제품 거래 0건일 때 비슷한 품목 찾기·업체명 탐색(`overview_probe`) 비용 확인 후 축소.
- 차가운 상태: 앱 기동 구간 측정 방법 마련(통합 담당과 재시작 일정 조율).

## 10. 재현 명령
```bash
PYTHONPATH="$PWD/src" ../../.venv/Scripts/python.exe -m pytest -q tests/test_track_b_db_quote_comparison.py tests/test_product_matching.py
gh workflow run track-b-search-timings.yml --ref main
```

## 11. 캡처
없음(숫자는 측정 문서).

## 12. 공통 파일 변경 요청
없음.
