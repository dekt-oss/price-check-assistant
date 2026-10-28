# 현재 운영 기준표 (정본)

기준 커밋: `a9ad7c2` 이후 (2026-10-28). 이 표가 운영 경로·시간 한도·매핑 수의 **정본**이다. 다른 문서와
다르면 이 표를 믿고 그 문서에 "대체됨" 링크를 단다. 표 4는 `tests/test_current_operations_doc.py`가
워크플로 파일과 대조하므로, 워크플로를 바꾸면 이 표도 같이 고쳐야 CI가 통과한다.

## 1. 데이터가 어디에 있나

| 자료 | 정본(지워지면 복구 불가) | 앱이 실제로 읽는 것 | 비고 |
| --- | --- | --- | --- |
| 나라장터 납품요구(Track B) | R2 `raw/` 원본 페이지(SHA-256 이름) | R2 `derived/v1/track-b-serving/` SQLite 인덱스 (약 4.6 GB, 앱이 임시폴더로 받아 씀) | 포인터는 R2 `state/` 에 있고 앱은 5분마다 확인한다. PostgreSQL은 운영에서 쓰지 않는다(개발용 대체 경로만) |
| 식약처 제품(Identity) | R2 원본 | R2 SQLite 인덱스 (약 2.1 GB) | 동기화 주기 아래 표 4 |
| 식약처 품목 상태 | R2 원본 | R2 SQLite 인덱스 | |
| 실시간 보강 거래 | 보관 안 함 | 조회 순간 응답 | "원문 위치"에 "보관 안 됨"으로 표시. 보관 원본은 다음 수집 뒤에 생긴다 |
| 병원 경영 회계 | `data/hospital_financial.csv` (KHIDI 공시 2016~2024) | 같은 파일 | 병상수는 심평원 키 활성화 대기 |
| 뉴스 | R2 `news/v1/` | 같은 곳 | 21일 보관 |
| 제품→나라장터 분류 매핑 | `data/g2b_product_mappings.csv` | 같은 파일 | 21개 중 **verified 10개** (테스트가 CSV와 대조) |

`docs/R2_RAW_EVIDENCE_STORAGE_V1.md`의 "PostgreSQL이 serving을 담당" 문장은 2026-09 설계안이며, 지금 운영의
나라장터 검색은 위 표처럼 R2의 SQLite 인덱스를 쓴다.

## 2. 운영 실행 환경

| 항목 | 값 | 확인 방법 |
| --- | --- | --- |
| 주소 | https://bp-price-research.streamlit.app | |
| 호스팅 | Streamlit Community Cloud, 메모리 한도 약 3.2 GB | `?_memdiag=1` 의 MEMORY_DIAGNOSTIC 줄 |
| Python | 3.14.9 (2026-10-28 v35에서 확인) | `?_memdiag=1` 의 RUNTIME 줄 |
| OS | Debian GNU/Linux 13 (trixie), x86_64, glibc 2.41 | 같은 줄 |
| 주요 패키지 | streamlit 1.66.1 · pandas 2.3.3 · SQLAlchemy 2.1.6 · pydantic 2.14.1 · pypdfium2 5.14.0 · tesseract-bin 1.1.0 | 같은 줄 (requirements.txt가 범위만 정하므로 재시작 때 바뀔 수 있다) |
| 패키지 설치 | `requirements.txt` (cloud가 uv로 설치) | |
| 배포 확인 | `pages/1_대시보드.py`의 숨은 표식 `purchase-workspace-runtime-vNN` | Production Browser Smoke가 머지 뒤 이 표식을 기다린다 |

CI는 두 가지 Python에서 돈다: 개발 기준 3.11(`ci.yml`의 `test`)과 운영과 같은 Python(`test-production-python`, 3.14).
`streamlit-cloud-build.yml`은 운영과 같은 `python:3.14-trixie` 컨테이너에서 requirements 설치를 재현한다.

## 3. 정해진 한도

| 한도 | 값 | 어디서 정하나 |
| --- | --- | --- |
| 나라장터 API 하루 호출 | 100,000 (2026-10-09 상향) | data.go.kr 계정 |
| 수집 작업 하루 상한 | 80,000 (앱 실시간 조회 몫을 남김) | `TRACK_B_DAILY_CALL_CAP` |
| 기간 조회 | 1년 초과 범위는 API가 거부(code 07) | 나라장터 API |
| 실시간 보강 | 수집 기준일 다음 날부터 오늘까지, 최대 `MAX_GAP_DAYS`일 | `track_b_live_gap_fill.py` |

## 4. 자동 작업 (워크플로)

시간은 UTC 기준 cron이다(KST = UTC+9). "작업 시간 한도"는 수집 job의 `timeout-minutes`다.

| 워크플로 파일 | cron | 작업 시간 한도(분) | 하는 일 |
| --- | --- | --- | --- |
| `track-b-daily-backfill.yml` | `10 18 * * *` | 240 | 최근 31일 재수집, 호출 6,000 |
| `track-b-history-backfill.yml` | `40 */3 * * *` | 175 | 2021-01-01~2025-09-11 과거분, 2,000건씩 최대 140분 반복 |
| `track-b-supplemental.yml` | `40 19 * * 0` | 30 | verified 분류 보충 수집, 호출 50 |
| `track-b-r2-serving-index.yml` | (수집 완료 뒤 자동) | 180 | 검색 인덱스 재생성·게시 |
| `mfds-identity-index.yml` | `23 0 * * *` | 120 | 식약처 제품 인덱스 |
| `mfds-item-status-index.yml` | `47 3 * * *` | 115 | 식약처 품목 상태 인덱스 |
| `news-radar-collect.yml` | `*/30 * * * *` | 80 | 뉴스 수집(다음 실행을 스스로 시작) |
| `hospital-weekly-report.yml` | `0 23 * * 0` | 15 | 주간 병원 리포트 |

나라장터 수집·게시 4종은 같은 잠금 그룹 `track-b-r2-pipeline`을 쓰고 `queue: max`로 줄을 선다
(한 번에 하나만 실행, 기다리는 실행은 취소되지 않음).

## 5. 이 표와 어긋났던 옛 문서

| 문서 | 옛 내용 | 지금 |
| --- | --- | --- |
| `README.md` | verified 매핑 5개, 경영 회계자료 미적재 | verified 10개, 2016~2024 적재 (2026-10-28 수정) |
| `docs/TRACK_B_DAILY_PIPELINE.md` | 과거분 수집 320분 | 최대 140분, 작업 한도 175분 (2026-10-28 수정) |
| `docs/R2_RAW_EVIDENCE_STORAGE_V1.md` | PostgreSQL이 serving 담당 | 운영 serving은 R2 SQLite 인덱스 (머리말에 대체 링크 추가) |
