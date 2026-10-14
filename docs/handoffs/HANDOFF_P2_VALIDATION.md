# HANDOFF P2 Validation — 성능 검증 증거 보강

## 1. 기준 커밋

- 운영 측정 소스 기준: `28a2fd7e597ab161197177c9d012bffe0b58c875`
- 최신 `origin/main`/문서 기준: `9c0072785342a697de13e9e5d417dbf9e57ff58e`
- 운영 화면은 runtime v24를 40/40 확인했지만 정확한 배포 Git SHA는 **미검증**이다.

## 2. 브랜치와 워크트리

- 브랜치: `codex/ux-v11-performance-uat-evidence`
- 워크트리: `C:\Users\임준혁\.codex\worktrees\ux-v11-performance-uat-evidence\price-check-assistant`
- main 체크아웃은 수정하지 않았다.

## 3. 수정 파일

- `docs/performance/UX_V11_PRICE_BASELINE.md`
- `docs/uat/UX_V11_INTEGRATION_UAT.md`
- `docs/handoffs/HANDOFF_P2_VALIDATION.md`
- `docs/handoffs/HANDOFF_I0_VALIDATION.md`

코드·테스트·워크플로 파일은 수정하지 않았다.

## 4. 실행 명령

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
python -m pytest -q tests/test_ux_v11_integration.py tests/test_streamlit_startup_smoke.py
python -m pytest -q
ruff check .
```

운영 표본은 Playwright Chromium에서 읽기 전용 검색만 실행했다. 표본마다 새 페이지를 사용했고 운영 Reboot·캐시 삭제·설정 변경은 하지 않았다.

## 5. 측정 환경

- 운영: `https://bp-price-research.streamlit.app`, Windows headless Chromium
- 시각: 2026-10-13 23:37~23:50 KST
- warm: 미집계 사전 검색 4회 뒤 모델별 10회
- local control: 2026-10-14 00:03 KST, 새 Streamlit 프로세스, R2 자격 증명 없음, 기존 OS 임시 인덱스 유지
- p95: nearest-rank

## 6. 실제 결과

- warm 브라우저 계측 40/40 결론 카드 도달, 계측 실패율 0%, runtime v24 확인. 데이터 부분 결과는 전용 마커가 없어 분류 불가
- wall p50/p95: PNB 10.370/13.057초, SJ 10.139/10.961초, HeartOn 16.116/19.755초, NT960 18.348/19.855초
- HeartOn 병목: `same_item_models` p50 4.641초, `category_market` 1.437초
- NT960 병목: `track_b_lookup` p50 10.346초
- PNB·SJ는 `wall-total` p50이 각각 7.823/7.881초로 서버 밖 구간이 더 큼
- 로컬 fresh-process/no-R2 대조군: 시작 85 MB, 완료 183 MB, wall 8.737초. 검색 중 진짜 피크와 full-index cold는 미확보

## 7. 인수 조건별 판정

| 조건 | 판정 |
| --- | --- |
| 모델별 n/min/p50/p95/max/실패율 | 됨 |
| warm 반복 표본 | 됨 |
| cold/warm 분리 | 부분 — warm 완료, 새 full-index cold 미확보 |
| 단계별 병목 | 됨 |
| 피크 메모리와 상한 비교 | 확인 불가 — 시작/완료만 관측, 피크·상한 미확보 |
| P2b 착수 판단 | 됨 — 네 모델 warm wall p50이 10초 초과 |

## 8. Claude 작업과 겹치지 않았다는 파일 목록 확인

변경 파일은 3절의 문서 4개뿐이다. 뉴스·병원 경영·가격 계산 코드, `Home.py`, `pages/*`, `scripts/*`, `tests/*`, `requirements.txt`, `pyproject.toml`, `.github/workflows/*`, 최종 리뷰 원문은 변경하지 않았다.

## 9. 미검증 항목

- 정상 R2 인덱스를 포함한 새 cold 표본
- 검색 중 진짜 RSS 피크와 운영 플랫폼 메모리 상한 비교
- 운영 서버의 정확한 Git SHA

## 10. 재개 지점

full-index cold와 피크 메모리를 다시 닫을 때는 운영을 재시작하지 말고, R2 읽기 설정이 있는 격리 로컬 환경에서 새 프로세스 1회만 실행한다. 검색 전/250ms RSS 샘플/완료 후를 한 로그에 남기고 `cold=1`과 인덱스 준비 시간을 함께 확인한다.

## 11. 공통 파일 변경 요청

없음. 피크 관측 자동화나 새 마커가 필요하더라도 이번 PR에서는 공통 코드 변경을 요청하거나 구현하지 않는다.

## 12. PR URL과 CI 상태

- PR: 생성 후 갱신
- 로컬 검증:
  - `ruff check .`: 통과
  - 타깃 통합·시작 스모크: `12 passed in 18.36s`
  - 외부 실패 주입: `5 passed in 2.99s`
  - 전체: `1827 passed, 14 failed, 3 warnings in 85.32s`
  - 실패 14건은 기존 Windows 실패군과 일치: OCR 실환경 4건, 견적 업로드/OCR 3건, cp949 7건. 신규 실패 0건
- CI: PR 생성 후 확인
