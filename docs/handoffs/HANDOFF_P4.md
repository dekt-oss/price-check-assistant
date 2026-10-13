# HANDOFF — Phase P4 (거래 기간 URL 보존)

## 1. 기준 커밋과 작업 브랜치
- 시작 `266c64b`(H2 후속 머지 뒤 main) · 브랜치 `claude/ux-v11-price`

## 2. Phase 목적
검색어는 주소(`?q=`)에 남아 새로 고침·공유 링크로 같은 결과가 열리지만, 고른 "거래 기간"(최근 3년 / 최근 5년 / 전체)은 새로 고침하면 기본값으로 돌아갔다. 고른 기간도 주소에 남겨 같은 화면이 다시 열리게 한다.

## 3. 완료한 요구사항
- 주소 표기 `?period=3y|5y|all` (최근 3년 / 최근 5년 / 전체). 대소문자·앞뒤 공백은 허용, 그 밖의 값은 무시하고 기본 동작(최근 3년, 거래가 없으면 넓히기)
- 기간을 고르면 주소에 `period`를 쓴다. 선택을 풀면 기본값(`3y`)을 쓴다
- 주소에 올바른 `period`가 있고 이 세션에서 그 결과의 기간을 아직 고르지 않았으면 그 기간으로 연다. 주소의 기간은 사람이 고른 것으로 보아 넓히지 않는다(`user_chose=True`)
- 같은 세션에서 이미 고른 기간이 주소보다 우선한다
- 새 검색(검색창 제출, 개요의 모델 열기, 허가 선택, 최근 검색·예시 클릭)은 고른 기간을 유지한다. "새 검색" 버튼은 기간까지 모두 지운다(기존 `clear()`)

## 4. 변경 파일
`pages/1_대시보드.py`, `src/purchase_price/ui/result_summary.py`, 테스트 `tests/test_price_period_url.py`(신규), 이 문서

## 5. 데이터 계약 변경
- `result_summary`: `PERIOD_URL_PARAM`, `PERIOD_URL_TOKENS`, `period_url_token`, `period_label_from_url`, `adopt_url_period`, `remember_picked_period`
- 런타임 마커 `PERIOD_URL_V1` — 대시보드 재적재 목록에 추가

## 6. 실행한 테스트
PR 본문에 적는다.

## 7. 미검증
- 운영 화면(머지·배포 뒤 확인). 대시보드 자체를 `?q=…&period=5y`로 여는 AppTest는 Track B 색인이 필요해 만들지 않았고, 같은 도우미를 같은 순서로 부르는 작은 페이지로 대신 확인했다.

## 8. 알려진 위험
- 주소의 `period`는 하나라 한 화면에 결과가 여럿이면(견적서 여러 품목) 마지막에 고른 기간이 새로 고침 뒤 모든 품목에 적용된다.
- 세션 안에서 결과 A의 기간을 고른 뒤 다른 결과에서 다른 기간을 고르고 A로 돌아오면, 화면은 A에서 고른 기간이고 주소는 마지막에 고른 기간일 수 있다(새로 고침하면 주소 쪽).

## 9. 다음 작업
- 머지·배포 뒤 운영에서 기간을 "최근 5년"으로 바꾸고 새로 고침해 그대로인지 확인.

## 10. 재현 명령
```bash
cd .worktrees/ux-v11-price
PYTHONPATH="$PWD/src" ../../.venv/Scripts/python.exe -m pytest -q tests/test_price_period_url.py tests/test_result_comparison_card.py tests/test_streamlit_startup_smoke.py tests/test_ux_v11_integration.py
```

## 11. 캡처
없음(로컬 화면 캡처 미실시).

## 12. 공통 파일 변경 요청
없음.
