# HANDOFF H2 — 병원 경영 브리핑

> H2 리뷰 후속 수정·로컬 검증 완료, 후속 PR/CI 전 · 운영은 구버전 확인 · 2026-10-13 KST

## 1. 기준 커밋과 작업 브랜치

- 작업지시서 BASE_SHA: `ecb888bada895fec30443a951dfc09ab2e90a54e`
- 작업 시작 시 `origin/main`: `e12e8bbdb71ceb6742bbf195e0ac3b4154cc36ea` (`[H1] Add hospital news issue clustering (#354)`)
- H2 작업 전 병합 커밋: `7aebb88d0723d77406a24550f4a206a14db305b1`
- 작업 브랜치: `codex/ux-v11-news-management`
- 워크트리: `.worktrees/ux-v11-news-management`
- H2 구현 커밋: 이 HANDOFF를 포함하는 PR HEAD
- H2 main 병합 커밋: `922cd97`
- H2 리뷰 후속 기준 main: `2ccd2b9`

## 2. Phase 목적

공개 회계자료에서 계산한 핵심 차이와 최근 변화를 짧은 경영 브리핑으로 먼저 보여 주고, 같은 브리핑을 화면·Markdown·Excel에서 재사용한다. 비교 근거가 부족하면 결론 대신 비교 보류를 표시한다.

## 3. 완료한 요구사항

- 첫 줄을 `YYYY 회계연도 공시 기준 · 비교병원 N곳`으로 고정했다.
- 지표별 유효 비교값 3곳 이상만 브리핑 후보로 쓰며, 부족하면 `비교 보류`로 표시한다.
- 비율은 `%p`, 금액은 비교군 평균 대비 `%`로 계산한다.
- 허용폭은 비율 ±1%p, 금액 ±5%이며, `절대 차이 ÷ 허용폭` 순서로 최대 3개를 고른다.
- 최근 연속 3년의 격차 방향이 일관된 지표를 최근 변화로 최대 2개 표시한다.
- 원인을 단정하지 않고 환자·진료단가·비용 구성·재무구조 등 추가 확인 자료만 안내한다.
- 화면 계층을 경영 브리핑 → 핵심 지표 → 의료수익·의료이익률 추이 → 비용 구조 → 전체 지표·자료 상태로 바꿨다.
- AI 설명은 키가 있을 때만 접힌 선택 기능으로 표시하고, 키가 없을 때 설정 부족 문구를 노출하지 않는다.
- 화면과 다운로드 리포트가 같은 `ManagementBriefing` 객체를 사용한다.
- 기준 병원 자료 없음, 비교군 없음, 유사 규모 기준 병상수 없음의 다음 행동 문구를 구분했다.
- 8개 기본 병원 × 비교군 5종 40조합에서 브리핑·Markdown·Excel 생성과 문장 제한을 검사했다.

## 4. 변경 파일 목록과 허용목록 대조

| 파일 | 핵심 변경 | 소유권 |
| --- | --- | --- |
| `src/purchase_price/services/hospital_metrics.py` | 결정적 브리핑 모델·정렬·보류·추가 확인·금지어 검사 | Track H 허용 서비스 |
| `src/purchase_price/services/hospital_benchmark.py` | 최근 변화 계산의 연도별 최소 유효 n, 런타임 마커 | Track H 허용 서비스 |
| `src/purchase_price/services/hospital_report.py` | 동일 브리핑을 Markdown·Excel 상단에 삽입 | Track H 허용 서비스 |
| `pages/21_병원_경영_Benchmark.py` | 상단 브리핑과 화면 계층·빈 상태·선택형 AI 정리 | Track H 허용 페이지 |
| `tests/test_hospital_metrics.py` | 산식·순위·상한·보류·빈 자료·조사·금지어 테스트 | Track H 허용 테스트 |
| `tests/test_hospital_benchmark.py` | AppTest 브리핑·보류 확인 | Track H 허용 테스트 |
| `tests/test_hospital_phase4.py` | 화면·리포트 일치, 40조합 Markdown·Excel 생성 | Track H 허용 테스트 |
| `docs/metrics/hospital_management.md` | H2 확정 계약·런타임 마커 반영 | Track H 허용 문서 |
| `docs/HOSPITAL_MANAGEMENT_BRIEFING_EXAMPLES_2026-10-13.md` | 병원·비교군별 예시와 40조합 상태표 | Track H 허용 문서 |
| `docs/handoffs/HANDOFF_H2.md` | 이 문서 | Track H 허용 문서 |

공통 파일, 가격 파일, `requirements.txt`는 수정하지 않았다.

## 5. 데이터 계약·API·인덱스 버전 변경

- 새 내부 객체: `hospital_metrics.ManagementBriefing`.
- 새 생성 함수: `build_management_briefing(rows, gap_history, fiscal_year, peer_count, ...)`.
- 기존 `describe_findings()`는 호환을 위해 유지했다.
- `hospital_benchmark.gap_history()`에 선택 인자 `min_peer_count`를 추가했다. 기본값 0이라 기존 호출 동작은 유지된다.
- `BenchmarkReport`에 `briefing` 필드를 추가했다. `build_report()`가 항상 이를 채운다.
- 저장 데이터·외부 API·뉴스 인덱스 형식은 바꾸지 않았다.
- 런타임 마커: `hospital_benchmark.MODULES_REVISION = "2026-10-13-h2"`.

## 6. 실행한 테스트와 실제 결과

- H2 RED: 새 요구 테스트 `9 failed, 22 passed`; 구현 전 실패를 확인했다.
- H2 집중 GREEN: `33 passed in 13.38s`.
- `ruff check .`: `All checks passed!`.
- `pytest -q tests/test_streamlit_startup_smoke.py`: `1 passed in 16.05s`.
- 작업지시서 Track H 지정 테스트: `183 passed, 1 warning in 29.03s`.
- 전체 `pytest -q`: `1780 passed, 14 failed, 1 warning in 93.48s`.
  - Windows에서 Tesseract·표준 폰트가 없는 OCR 실환경 4건.
  - 견적 OCR fallback·업로드 관련 가격 영역 3건.
  - Windows 기본 cp949로 UTF-8 가격 워크플로 파일을 읽는 가격 영역 7건.
  - H2 허용목록 파일에서 발생한 실패는 없다.
- 로컬 포트 8603 브라우저: 기본 지역 비교군에서 상단 3개 차이 문장과 추가 확인 안내, 동일 유형 2곳에서 `비교 보류`, 그래프·비용 구조·자료 상태 순서를 확인했다.
- H2 리뷰 후속 RED: `6 failed, 22 passed`로 단위 혼합 순위·방향 누락·병상수 기준 누락·상태 문구·반올림 경계·캐시 미구현을 재현했다.
- H2 리뷰 후속 집중 GREEN: `28 passed in 5.20s`.
- 병원 화면·지표·리포트·계약 회귀: `58 passed, 1 warning in 26.27s`.
- 작업지시서 Track H 지정 테스트: `195 passed, 1 warning in 83.24s`.
- 최종 H2 집중 회귀: 시작 스모크의 15초 시간 초과 1건을 제외하고 `38 passed`; 시작 스모크 단독 재실행은 `1 passed in 25.52s`.
- 전체 `pytest -q`: `1793 passed, 15 failed, 1 warning in 219.79s`.
  - 기존 Windows OCR·견적 OCR/업로드·cp949 가격 워크플로 실패 14건.
  - 가격 영역 AppTest 시간 초과 1건은 단독 재실행에서 `1 passed in 10.49s`로 통과했다.
  - H2 허용목록 파일에서 발생한 실패는 없다.

## 7. 미검증 항목

- H2 PR CI: PR 생성 전이라 미검증.
- main 병합과 운영 배포: 미실행.
- 운영 `/hospital-benchmark` 화면과 다운로드 파일: 머지 전이라 미검증.
- API 키가 있는 실제 AI 설명 호출: 선택 기능이며 유료 외부 호출을 실행하지 않아 미검증.
- 주간 Actions가 새 리포트를 실제 생성·R2 업로드하는 과정: 미실행.
- 2026-10-13 운영 `/hospital-benchmark` 직접 확인에서는 여전히 `병원 경영 Benchmark`와 구 화면이 보여 H2 배포 반영은 미검증이 아니라 **미반영 확인** 상태다. Streamlit Reboot 뒤 재확인이 필요하다.

## 8. 알려진 위험과 Fable Review

- Fable Review 중 중간 심각도 2건을 재현하고 조치했다.
  1. 기준 병원 자료가 모두 없을 때 비교병원 부족으로 잘못 설명하던 문제를 전용 상태 문구로 분리했다.
  2. 모음으로 끝나는 지표에서 `병상당 인건비은`처럼 조사가 어색해지는 문제를 받침 규칙으로 고쳤다.
- 재료비는 기존 계약대로 약품비·진료재료비 중 한 항목만 있어도 부분 합산한다. 부분 합산 여부를 별도 표식으로 보여 주지는 않으며 H2에서 산식을 바꾸지 않았다.
- 비교병원 수 첫 줄은 사용자가 선택한 병원 수이고, 핵심 표의 `비교 병원 수`는 지표별 유효값 수다. 둘은 의도적으로 다를 수 있다.
- 전체 로컬 pytest의 지속 실패 14건은 Track H 밖의 기존 Windows 환경·인코딩 실패다. 추가 AppTest 시간 초과 1건은 단독 재실행에서 통과했으며, 병합 판단은 CI 결과를 기준으로 해야 한다.
- H2 리뷰 후속 Fable Review에서 페이지 캐시 키 인자를 `_source_revision`으로 작성해 Streamlit 해시에서 제외되는 결함을 AppTest가 잡았다. 인자명을 `source_revision`으로 바꿔 원천 파일 경로·mtime·크기가 캐시 키에 포함되게 했고, 같은 테스트 묶음 `58 passed`로 닫았다.

## 9. 다음 Phase 시작 지점

PR CI가 녹색이면 main에 스쿼시 병합한 뒤 운영 `/hospital-benchmark`에서 브리핑·비교 보류·다운로드를 확인한다. 이후 Integration I0-b가 홈의 최신 경영 브리핑 상태와 전체 화면 폭·키보드 UAT를 맡는다.

## 10. 재현 명령

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
streamlit run Home.py --server.port 8603
```

```powershell
ruff check .
pytest -q tests/test_streamlit_startup_smoke.py
pytest -q tests/test_news_radar.py tests/test_news_radar_index.py tests/test_news_radar_page.py tests/test_news_radar_workflow_contract.py tests/test_news_relevance_and_alerts.py tests/test_news_subscriptions.py tests/test_collect_news_radar.py tests/test_naver_news_client.py tests/test_next_news_radar_run.py tests/test_hospital_benchmark.py tests/test_hospital_intelligence_phase1_contract.py tests/test_hospital_master.py tests/test_hospital_metrics.py tests/test_hospital_phase4.py tests/test_khidi_financials.py tests/test_alio_disclosure.py tests/test_hira_hospital_info.py
pytest -q
```

## 11. 캡처·결과 예시 경로

- 병원·비교군별 결과 예시: `docs/HOSPITAL_MANAGEMENT_BRIEFING_EXAMPLES_2026-10-13.md`.
- 로컬 기본 비교군과 비교 보류 화면: 2026-10-13 KST에 포트 8603 브라우저 캡처로 확인했다. 소유권 허용목록에 이미지 저장 경로가 없어 저장소에는 바이너리 캡처를 추가하지 않았다.
- 운영 캡처: PR 병합·배포 뒤 확인해야 한다(미검증).

## 12. 공통 파일 변경 요청

- Integration I0-b가 `pages/0_홈.py`에 `최신 경영 브리핑 상태`를 연결할 때 `build_report(...).briefing`의 `heading`, `status`, `differences`를 사용한다. Track H는 소유권 경계를 지키기 위해 홈 파일을 수정하지 않았다.
- 운영 스모크에 `/news-radar`의 `최근 3일 주요 이슈`와 `/hospital-benchmark`의 `병원 경영 비교` 제목 확인을 추가하는 작업은 Integration I0-b 범위다.

## 13. Claude H2 리뷰 후속 조치

- 최근 변화 순위를 비율 `%p ÷ 1%p`, 금액 `비교군 평균 대비 변화율 ÷ 5%`로 정규화했다.
- 최근 변화 문장에 비교군 평균보다 높은 쪽인지 낮은 쪽인지 표시한다.
- 병상당 지표가 브리핑에 포함되면 회계공시 병상수 우선·심평원 허가병상수 보완 기준을 추가 확인 줄에 표시한다.
- `ManagementBriefing.lines`를 화면과 같은 상태 → 차이 → 추세 → 추가 확인 순서로 맞췄다.
- 일부 지표가 비교 보류이고 나머지에 허용폭 초과가 없으면 두 안내를 함께 표시한다.
- 허용폭 판정과 화면 표기를 같은 소수 첫째 자리 반올림 값으로 맞췄다.
- 40조합 테스트가 `master_service.PEER_GROUP_LABELS`를 직접 읽도록 바꿨다.
- 페이지 데이터와 전체 리포트에 원천 파일 revision 기반 `st.cache_data`를 적용했고, 다운로드 생성 시각은 현재 시각으로 다시 채운다.
- 운영 Reboot와 공통 운영 스모크 수정은 외부 운영·Integration 범위라 실행하지 않았다.
