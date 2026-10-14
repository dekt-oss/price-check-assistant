# HANDOFF I0 Validation — Integration UAT 잔여 검증

## 1. 기준 커밋

- 브라우저 검증 소스 기준: `28a2fd7e597ab161197177c9d012bffe0b58c875`
- 최신 `origin/main`/문서 기준: `9c0072785342a697de13e9e5d417dbf9e57ff58e`
- 성능 화면 runtime v24는 확인했으나 뉴스 화면의 정확한 배포 Git SHA는 **미검증**이다.

## 2. 브랜치와 워크트리

- 브랜치: `codex/ux-v11-performance-uat-evidence`
- 워크트리: `C:\Users\임준혁\.codex\worktrees\ux-v11-performance-uat-evidence\price-check-assistant`

## 3. 수정 파일

- `docs/performance/UX_V11_PRICE_BASELINE.md`
- `docs/uat/UX_V11_INTEGRATION_UAT.md`
- `docs/handoffs/HANDOFF_P2_VALIDATION.md`
- `docs/handoffs/HANDOFF_I0_VALIDATION.md`

## 4. 실행 명령

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
python -m pytest -q `
  tests/test_device_page_ui.py::test_failed_lookup_notice_hides_urls_and_keys `
  tests/test_safety_support.py::test_recall_lookup_failure_is_check_failed_not_zero `
  tests/test_production_runtime_research_safety.py::test_mfds_failure_kind_is_secret_safe_and_actionable `
  tests/test_production_runtime_research_safety.py::test_uncaught_mfds_code_30_exception_keeps_not_authorized_semantics `
  tests/test_data_go_kr_transport.py::test_exhausted_transport_retry_is_wrapped_and_secret_redacted
```

## 5. 측정 환경

- 운영 URL, Chromium viewport 에뮬레이션
- 뉴스: 1024×900
- 가격: PNB-704 최근 5년, 같은 세션에서 390×844 → 1280×900 → 390×844 → 새로고침
- 외부 실패: 로컬 dependency/예외 주입. 운영 장애 유발 없음

## 6. 실제 결과

- 뉴스: 문서 `scrollWidth=clientWidth=1024`, 오른쪽 경계 밖 요소 0. 상단 지표, 주요 이슈, 관련 기사 접기, 키워드 설정, 최신 기사 영역 확인
- 가격: 문서 가로 넘침 0. 그래프 2개가 362→878→362px로 재계산되고 새로고침 뒤 362px 유지. 이전 기록의 폭 고정 잘림은 현재 운영에서 재현되지 않음
- 표: 페이지 밖 넘침 없이 데이터프레임 내부에 9px 스크롤 존재
- 외부 실패: 지정 테스트 `5 passed in 2.99s`; 실패/0건 의미 분리, 비밀값·URL·내부 예외 비노출 확인

## 7. 인수 조건별 판정

| 조건 | 판정 |
| --- | --- |
| 병원 뉴스 1024px | 됨(브라우저 에뮬레이션) |
| 가격 폭 변경·새로고침 | 됨(브라우저 에뮬레이션) |
| 실제 기기 회전 | 확인 불가 |
| 외부 조회 실패 상태 | 부분 — 로컬 실패 주입 통과 / 운영 미검증 |
| 기존 기록과 다른 판정 보존 | 됨 — 날짜 있는 후속 표로 추가 |

## 8. Claude 작업과 겹치지 않았다는 파일 목록 확인

변경 파일은 문서 4개뿐이다. `news_radar*`, `news_issues.py`, 뉴스 수집 스크립트·페이지·테스트, `hospital_*`, 병원 경영 페이지·테스트, 뉴스/병원 metric 문서, `pages/1_대시보드.py`, 통합 스모크 스크립트는 변경하지 않았다.

## 9. 미검증 항목

- 실제 휴대폰·태블릿 회전과 터치 조작
- 운영에서 실제 외부 장애가 발생했을 때의 화면
- 뉴스 운영 코드의 정확한 배포 Git SHA
- 뉴스 군집 내용 정확성(이번 범위 밖)

## 10. 재개 지점

실제 기기 검증이 가능할 때 PNB-704 최근 5년을 세로→가로→세로로 회전하고, 새로고침 전후 그래프·표 너비와 터치 스크롤을 확인한다. 운영 외부 실패는 자연 장애가 관찰될 때만 증거를 추가하며 장애를 인위적으로 만들지 않는다.

## 11. 공통 파일 변경 요청

없음.

## 12. PR URL과 CI 상태

- PR: 생성 후 갱신
- 로컬 검증:
  - `ruff check .`: 통과
  - 타깃 통합·시작 스모크: `12 passed in 18.36s`
  - 외부 실패 주입: `5 passed in 2.99s`
  - 전체: `1827 passed, 14 failed, 3 warnings in 85.32s`
  - 실패 14건은 기존 Windows 실패군과 일치: OCR 실환경 4건, 견적 업로드/OCR 3건, cp949 7건. 신규 실패 0건
- CI: PR 생성 후 확인
