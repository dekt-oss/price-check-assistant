# HANDOFF H1 — 병원 뉴스 주요 이슈

> (당시 상태) H1 리뷰 후속 수정 진행 · 운영 재검증 전 · 2026-10-13 KST
>
> **최종 상태(2026-10-13 저녁):** #354·#356·#362 머지, 운영 반영·스모크 통과, 새 규칙 수집 뒤 운영 상위 5개 확인. 현재 판정은 `docs/coordination/UX_V11_FINAL_REVIEW.md`를 본다. 본문 7장의 미검증 목록은 당시 기록이다.

## 1. 기준 커밋과 작업 브랜치

- 작업지시서 BASE_SHA: `ecb888bada895fec30443a951dfc09ab2e90a54e`
- H0 보완 main 커밋: `2502f76453976d24f18b85eb9191731eb9872b48`
- PR #341 main 커밋: `8a84477c42fb7ab351fc2680a66922ddcff21f19`
- H1 구현 커밋: `adc0a78`
- H1 리뷰 후속 커밋: `576409d`
- H1 리뷰 후속 PR: `#356` (CI 3/3 통과, 병합 전)
- 작업 브랜치: `codex/ux-v11-news-management`
- 워크트리: `.worktrees/ux-v11-news-management`

## 2. Phase 목적

제목이 다른 반복 보도를 같은 사건 단위로 묶어 사용자가 먼저 확인할 병원 뉴스 이슈를 최대 5개로 보여 준다. 허용된 NAVER 표시 필드만 쓰며 새 요약 문장을 만들지 않는다.

## 3. 완료한 요구사항

- 운영 화면 중요도순 50건을 수작업으로 7개 반복 이슈 29건과 단독 21건으로 분류했다.
- 제목 핵심 토큰, 문자 2-gram, 96시간 전체 창, 키워드 그룹으로 결정적 군집 함수를 구현했다.
- 종합 소식 제목은 다른 기사와 자동 결합하지 않는다.
- 기사 수 자체가 아닌 기존 기사 중요도, 규제·회수 키워드, 서로 다른 매체 수, 최근성으로 이슈를 정렬한다.
- 수집 과정이 매번 이슈를 계산해 인덱스 v2에 저장한다. 앱 화면은 저장된 이슈만 읽는다.
- v1 payload와 `news-radar-index-v1` R2 메타데이터를 계속 읽는다.
- 화면 상단에 `오늘의 주요 이슈` 최대 5개와 분류, 매체·기사 수, 최초·최근 시각, 대표 기사, 관련 기사 접기를 추가했다.
- #341의 단순 화면, 기존 기사 목록, 문자·이메일 준비 중 안내, 기존 즉시 알림·일일 요약을 유지했다.
- 제목 불일치 결과를 `본문에서만 언급`으로 단정하지 않고 `제목에 키워드 없음`으로 바꿨다.
- 일부/전체 직접 수집 실패 문구에서 내부 오류를 제거하고 다음 행동을 안내한다.
- 상태 저장 능력을 확인하기 전 영구 저장을 단정하지 않는 중립 문구로 바꿨다.

## 4. 변경 파일 목록과 허용목록 대조

| 파일 | 핵심 변경 | 소유권 |
| --- | --- | --- |
| `src/purchase_price/services/news_radar.py` | 이슈 모델·군집·점수·런타임 마커 | Track H 허용 서비스 |
| `src/purchase_price/services/news_radar_index.py` | 인덱스 v2, 이슈 직렬화, v1 호환, 수집 시 계산 | Track H 허용 서비스 |
| `pages/20_병원_News_Radar.py` | 주요 이슈 UI·빈 상태·중립 문구 | Track H 허용 페이지 |
| `tests/test_news_radar.py` | 군집·시간 창·중요도 테스트 | Track H 허용 테스트 |
| `tests/test_news_radar_index.py` | v2 왕복·v1 payload/R2 메타데이터 호환 | Track H 허용 테스트 |
| `tests/test_news_radar_page.py` | 주요 이슈·빈 상태·중립 문구 AppTest | Track H 허용 테스트 |
| `docs/metrics/news.md` | H1 확정 계약 반영 | Track H 허용 문서 |
| `docs/NEWS_ISSUE_CLUSTER_EVAL_2026-10-13.md` | 50건 표본 평가표 | 작업지시서 H1 필수 산출물 |
| `docs/handoffs/HANDOFF_H1.md` | 이 문서 | Track H 허용 문서 |

공통 파일, 가격 파일, `requirements.txt`는 변경하지 않았다.

## 5. 데이터 계약·API·인덱스 버전 변경

- 저장 경로는 그대로 `news/v1/index.json.gz`다.
- payload `version`은 1에서 2로 올렸다. R2 메타데이터 스키마는 `news-radar-index-v2`다.
- v2의 `issues`는 `issue_id`, 대표 원문 `title`, `article_ids`, `group_keys`, `group_names`, `source_count`, `article_count`, `first_published_at`, `latest_published_at`, `representative_article_id`, 내부 `score`만 가진다.
- 기사 payload 필드는 바꾸지 않았다. 본문·검색 결과 설명·생성형 모델 결과·사용자 상태는 이슈 입력과 payload에 없다.
- v1 payload와 v1 R2 메타데이터는 읽으면 `issues=()`로 처리하고 다음 수집 때 v2로 갱신한다.
- H1 리뷰 후속 런타임 마커 `news_radar.MODULES_REVISION`과 페이지 `NEWS_PAGE_REVISION`은 `2026-10-13-h1-review`다.

## 6. 실행한 테스트와 실제 결과

- 리뷰 지적을 테스트로 먼저 고정한 RED 확인: `8 failed, 42 passed`.
- H1 후속 수정 집중 회귀 4개 파일: `51 passed in 13.71s`.
- 최종 H1 집중 회귀 + Streamlit 시작 테스트(`--basetemp .local/pytest-h1-final`): `52 passed in 32.66s`.
- H1 뉴스·계약·시작 회귀: `121 passed, 1 warning in 32.38s`.
- 작업지시서 Track H 지정 테스트: `190 passed, 1 warning in 33.57s`.
- `ruff check .`: `All checks passed!`.
- 전체 `pytest -q`: `1789 passed, 14 failed, 1 warning in 135.70s`.
  - 알려진 Windows OCR 실환경 실패 4건.
  - 견적 OCR/업로드 관련 가격 영역 3건.
  - Windows 기본 cp949로 UTF-8 가격 워크플로 파일을 읽는 가격 영역 7건.
  - H1 허용목록 파일에서 발생한 실패는 없었고, 소유권 밖 파일은 수정하지 않았다.
- 기본 pytest 임시 폴더와 `C:\tmp`는 현재 샌드박스에서 접근이 거부되어, 최종 집중 회귀는 워크트리 내부 전용 임시 경로로 재실행했다. 전용 경로는 실행 후 삭제했다.
- Streamlit AppTest: 주요 이슈 카드·접기·빈 상태·기존 목록을 확인했다.
- 로컬 포트 8602 브라우저 점검: 3건/2건/1건 이슈 카드, 알림 준비 안내, 기존 메뉴를 화면에서 확인했다.

## 7. 미검증 항목

- H1 리뷰 후속 PR #356 CI: `test`, `bundled-ocr`, `golden-uat` 3/3 통과.
- main 병합과 운영 배포: 미실행.
- 운영 인덱스 v2 생성과 실제 2,432건 전체 군집: 첫 배포 뒤 수집 Job 실행 전이라 미검증.
- 운영 `/news-radar` 주요 이슈 캡처: 머지 전이라 미검증.
- 운영 R2 상태 객체의 쓰기 권한: 상태 변경을 일으키지 않아 미검증.

## 8. 알려진 위험과 Fable Review

- 50건 표본에서는 잘못 묶임 0/1,171쌍, 누락 0/54쌍이지만 전체 기사 정확도를 뜻하지 않는다.
- 제목 표현이 새로 생기면 군집 누락이 생길 수 있다. 원문 문장을 생성하거나 의미 추론으로 보완하지 않는다.
- Fable Review에서 중간 심각도 1건을 찾았다. 90시간 간격 기사 세 개가 연쇄 연결되면 이슈 전체가 96시간을 넘는 문제였다. 결합 전 구성요소의 최초~최근 시각이 96시간 안인지 검사하고 회귀 테스트를 추가해 닫았다.
- Claude 리뷰의 H-2, M-1, M-3, M-4, L-1, L-2, L-3은 재현 테스트를 추가하고 수정했다. 출처 등급 전달, 최근 72시간 제한, 제목 특징 재사용, 손상 이슈 격리, 제목 기반 규제 가점, 설정 기반 종합 소식 구분어, Markdown 링크 안전화를 확인했다.
- H-1은 현재 v2를 되돌리지 않고 이후 스키마 변경에 `리더 선배포 → 운영 확인 → 라이터 전환` 절차를 적용하도록 문서화했다. 현재 운영 프로세스가 구버전 모듈을 유지 중인지는 Reboot 전이라 미검증이다.
- M-2의 별도 홀드아웃 평가는 최신 workflow artifact에 인덱스가 없고 로컬 R2도 설정되지 않아 실행하지 못했다. 기존 파라미터는 변경하지 않았다.
- 그 밖의 Critical/High 결함은 재현되지 않았다. v1 호환, 종합 기사 분리, 같은 병원 다른 사건 분리, 알림·요약 유지, 빈 상태를 점검했다.

## 9. 다음 Phase 시작 지점

H1 PR을 main에 병합하고 첫 뉴스 수집 Job이 v2 인덱스를 쓴 뒤 운영 화면을 확인한다. 그 다음 H2는 `services/hospital_metrics.py`의 결정적 문장 생성과 `pages/21_병원_경영_Benchmark.py`의 정보 계층부터 시작한다.

## 10. 재현 명령

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
$env:NEWS_RADAR_INDEX_PATH = '.local/news-radar.json.gz'
python -m purchase_price.scripts.collect_news_radar --output .local/news-radar.json.gz --no-alert
streamlit run Home.py --server.port 8602
```

```powershell
ruff check .
pytest -q tests/test_streamlit_startup_smoke.py
pytest -q tests/test_news_radar.py tests/test_news_radar_index.py tests/test_news_radar_page.py tests/test_news_radar_workflow_contract.py tests/test_news_relevance_and_alerts.py tests/test_news_subscriptions.py tests/test_collect_news_radar.py tests/test_naver_news_client.py tests/test_next_news_radar_run.py tests/test_hospital_benchmark.py tests/test_hospital_intelligence_phase1_contract.py tests/test_hospital_master.py tests/test_hospital_metrics.py tests/test_hospital_phase4.py tests/test_khidi_financials.py tests/test_alio_disclosure.py tests/test_hira_hospital_info.py
pytest -q
```

## 11. 캡처·결과 예시 경로

- 표본 평가: `docs/NEWS_ISSUE_CLUSTER_EVAL_2026-10-13.md`.
- 로컬 주요 이슈 화면: 2026-10-13 KST에 Codex 브라우저 캡처로 확인했다. 소유권 허용목록에 이미지 저장 경로가 없어 저장소에는 바이너리 캡처를 추가하지 않았다.
- 운영 캡처: H1 병합·v2 수집 뒤 이 절에 확인 결과를 추가해야 한다(미검증).

## 12. 공통 파일 변경 요청

없음.

## 13. Claude H1 리뷰 후속 조치

- 수집 Job이 `data/news_sources.json`의 출처 등급을 이슈 군집에 전달하도록 수정했다.
- 회수·판매중지·리콜·안전성 가점은 매칭 키워드와 기사 제목을 함께 확인한다.
- 상단 이슈는 최근 보도 시각 72시간 안으로 제한하고 제목을 `최근 3일 주요 이슈`로 바꿨다.
- 기사별 제목 토큰·2-gram은 한 번만 계산해 쌍 비교에서 재사용한다.
- 파생 이슈 한 건이 깨져도 원본 기사와 정상 이슈는 계속 읽는다.
- 종합 소식 구분어를 `data/news_keywords.json`의 `issue_roundup_terms`로 옮겼다.
- 관련 기사 Markdown 링크 제목의 대괄호를 중립화한다.
- 다음 인덱스 변경은 리더 먼저 배포하고 운영 반영을 확인한 뒤 라이터를 바꾸는 규칙을 `docs/metrics/news.md`에 추가했다. 현재 v2 형식은 되돌리지 않았다.
- 최신순·전체 그룹 50건 홀드아웃은 로컬 운영 인덱스와 R2 설정이 없어 미실행이다. 파라미터는 변경하지 않았다.
- 운영 Streamlit Reboot는 외부 운영 변경이므로 실행하지 않았다. `/news-radar` 운영 화면은 후속 배포 뒤 다시 확인해야 한다.

## 14. H1 후속 2 (통합 담당 Claude 대행, 2026-10-13 저녁)

- Codex 로컬에 운영 인덱스·R2 설정이 없어 미실행이던 홀드아웃을 통합 쪽에서 실행했다. 최신순 50건에서 업계 일반어만 겹친 세 회사 소식이 한 이슈(13건)로 묶이는 오결합을 확인했다.
- 조치: `news_radar._TITLE_STOPWORDS`에 업계 일반어와 의료AI·의료진·의료계 추가. 군집 규칙(공통 토큰 2 + Dice 0.18 + 96시간 + 그룹 교집합)은 유지.
- 결과: 중요도순 50건 0/0 유지, 최신순 50건 잘못 묶임 0/1,170쌍, 누락 14/55쌍(같은 매체의 기획 연재를 못 묶음 — 다음 과제). 상세 `docs/NEWS_ISSUE_CLUSTER_EVAL_2026-10-13.md` 2차 평가.
- 회귀 테스트 1개 추가, 기존 제목 변형 테스트의 예시 제목을 고유어가 겹치도록 조정. 런타임 마커 `2026-10-13-h1-review2`, 배포 마커 v24.
