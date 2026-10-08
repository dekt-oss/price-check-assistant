# AI Hospital Intelligence — Phase 1 구현 상태 (2026-10-08)

기획서: 「병원 News Radar + Hospital Benchmark 구현 기획서 (AI 업무지원 통합플랫폼 확장 모듈)」.
이 문서는 기획서의 Phase 1(통합 홈 화면 · News Radar 기본화면 · Benchmark 기본화면)이 코드로
어떻게 들어갔는지, 무엇이 되고 무엇이 아직 안 되는지를 적는다.

## 화면

| 화면 | 파일 | 주소 | 상태 |
| --- | --- | --- | --- |
| 통합 홈 (AI Hospital Intelligence) | `pages/0_홈.py` | `/home` | 동작 |
| 구매가격 조사 (기존) | `pages/1_대시보드.py` | `/` (기본) | 변경 없음 |
| 병원 News Radar | `pages/20_병원_News_Radar.py` | `/news-radar` | 동작 (NAVER 키 필요) |
| 병원 경영 Benchmark | `pages/21_병원_경영_Benchmark.py` | `/hospital-benchmark` | 틀만 동작 (회계자료 미적재) |

기본 주소(`/`)는 그대로 구매가격 조사 화면이다. 운영 스모크와 구매팀 즐겨찾기가 루트 주소에서
"통합 검색" 입력칸을 기대하므로 통합 홈은 `/home`에 두고 왼쪽 메뉴 맨 위에 넣었다.

## News Radar

- 키워드 그룹 5개(우리병원 · 경쟁·Benchmark 병원 · 병원경영 · AI·디지털 · 구매·관리)와 알림 방식은
  `data/news_keywords.json`에 있다. 화면에서 그룹별로 켜고 끌 수 있다(세션 안에서만 유지).
- "새 기사 확인" 버튼이 NAVER 뉴스 검색 API(날짜순, 키워드당 최대 30건)를 호출하고,
  원문 주소 기준으로 이미 본 기사를 걸러 새 기사만 센다. 같은 기사가 여러 키워드에 걸리면 한 건으로 합친다.
- 기사별 상태: 새 기사 / 읽음 / 중요 / 관심없음. 상단에 오늘 · 이번 주 · 중요 표시 · 아직 안 읽음 건수.
- 운영 설정(`NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`)이 없으면 안내문만 보이고 키워드 관리는 그대로 된다.
- 키는 **NAVER API HUB**(네이버클라우드 콘솔) 기준이다: 주소 `https://naverapihub.apigw.ntruss.com/search/v1/news`,
  헤더 `X-NCP-APIGW-API-KEY-ID` / `X-NCP-APIGW-API-KEY`. Application에서 "검색 > 뉴스" API를 켜지 않으면
  401 "요청한 API는 이 Application에서 활성화되어 있지 않습니다"가 난다. 옛 developers.naver.com 키는
  `NAVER_API_STYLE=developers`로 2027-06까지 쓸 수 있다.

### 네이버 검색 API 이용약관 분리 (2026-09-07 개정)

- 검색결과는 제목 · 게시시간 · 원문/네이버 링크 · 출처 도메인만 화면에 그대로 보여 준다.
- 검색결과를 AI 요약·분류·학습에 넘기지 않는다. 클라이언트는 `description` 필드를 아예 읽지 않는다
  (`tests/test_hospital_intelligence_phase1_contract.py`가 화면 코드에 AI 호출이 없음을 확인).
- Phase 1은 서버에 저장하지 않는다(세션 메모리). Phase 2에서 `news_item`에 저장할 때는 21일 보관 제한을 지킨다.
- AI 분석은 언론사 RSS·기관 보도자료 등 허용된 원자료만 쓰는 별도 레이어로 만든다(Phase 2 이후).

## Hospital Benchmark

- 병원 Master seed `data/hospital_master.json`: 부산백 · 해운대백 · 일산백 · 상계백 · 부산대 · 양산부산대 ·
  동아대 · 고신대복음 8개 병원. 표준명 · 별칭 · 법인 · 의료원 · 지역 · 종별 · 설립형태.
  **병상수는 비워 두었다**(심평원 자료 연계 전까지 추정값을 넣지 않는다). 종별도 `type_verified: false`.
- 비교군: 지역 경쟁군 / 동일 의료원 / 유사 규모(병상 ±100, 병상수 없으면 비교 불가 안내) / 동일 유형 /
  직접 선택(2~10개).
- 지표 계산(`services/hospital_metrics.py`)은 모두 코드가 한다: 의료이익률 · 순이익률 · 인건비율 · 재료비율 ·
  약품비율 · 진료재료비율 · 관리운영비율 · 부채비율 · 유동비율 · 차입금 비중 · 의료수익 증가율 · 3/5년 CAGR ·
  병상당 의료수익/인건비/재료비. 입력이 없으면 `None`("자료 없음")이고 어떤 값도 추정하지 않는다.
  비교군 평균과 위치(평균 이상/평균/평균 이하, 비용 지표는 높은 편/낮은 편)도 코드가 정한다.
- 회계자료는 아직 적재하지 않았으므로 화면의 지표 표는 전부 "자료 없음"이다. 5년 추이도 자리만 있다.

## DB

Alembic 0005가 기획서 6장의 테이블을 만든다: `hospital_master`, `hospital_financial`, `hospital_metric`,
`news_keyword`, `news_item`, `data_source_log`. Phase 1 화면은 아직 이 테이블을 읽지 않는다
(운영 Streamlit Cloud에는 PostgreSQL이 없고 seed 파일과 세션 메모리로 동작).

## 검증

- `tests/test_naver_news_client.py` — 헤더·파라미터·오류 처리, 키가 오류 메시지에 안 들어감.
- `tests/test_news_radar.py` — 그룹 켜고 끄기, 주소 정규화 중복제거, 신규 탐지, 상태 유지, 집계.
- `tests/test_hospital_master.py` — 별칭 해석, 비교군 5종.
- `tests/test_hospital_metrics.py` — 비율·증가율·CAGR·비교 위치·회계기간 경고.
- `tests/test_hospital_intelligence_phase1_contract.py` — 루트 주소 유지, 화면 용어, AI 미사용, 마이그레이션.
- `tests/test_streamlit_startup_smoke.py` — 새 화면 3개 포함 전체 페이지 기동.

## Phase 2 — News Radar 자동 수집 (2026-10-08)

운영(Streamlit Cloud)에는 PostgreSQL이 없고 앱은 R2 읽기 전용 키만 가진다. 그래서 저장소는 R2 객체이고,
쓰기는 GitHub Actions(쓰기 키)만 한다.

| 무엇 | 어디 | 누가 쓰나 |
| --- | --- | --- |
| 기사 목록 (버전 1, gzip JSON) | R2 `news/v1/index.json.gz` | 수집 Job (30분마다) |
| 읽음·중요·관심없음 상태 | R2 `news/v1/status.json` (기사 주소별) | 화면 (쓰기 권한이 있을 때만) |
| 하루 요약 (markdown) | R2 `news/v1/digest/YYYY-MM-DD.md` + Job 요약 화면 | 요약 Job (매일 08:30 KST) |

- 코드: `services/news_radar_index.py`(형식·병합·21일 정리·상태·알림문·요약문·저장소),
  `scripts/collect_news_radar.py`(수집/요약 CLI), `.github/workflows/news-radar-collect.yml`.
- 기사 목록 형식: `{version, generated_at, retention_days, keywords[...], items[...], runs[...]}`.
  `items`는 화면 표시 필드만(제목·원문/네이버 링크·출처 도메인·게시시간·걸린 키워드·처음 찾은 시각).
  `runs`는 최근 48회 실행 요약이고, 마지막 실행만 키워드별 기록(`data_source_log`와 같은 필드:
  source_name, query_text, ok, result_count, error_message, started_at, finished_at)을 둔다.
- 병합: 원문 주소 기준으로 중복을 합치고 처음 찾은 시각을 유지한다. 21일 보관 제한 때문에 게시·발견이
  21일 지난 기사는 지우고, 21일보다 먼저 게시된 기사는 처음부터 넣지 않는다(지웠다가 다시 "새 기사"로
  알리는 일을 막음). 목록에서 빠진 기사의 상태도 수집 때 함께 지운다. 21일 지난 하루 요약 파일도 지운다.
- 수집: 켜진 그룹의 키워드마다 NAVER 날짜순 최대 100건. 429(요청 과다)는 2·4·8초 쉬고 다시 시도한다.
  모든 키워드가 실패하면 Job을 실패로 끝낸다.
- 즉시 알림: `alert: immediate` 키워드에 새 기사가 있으면 `NEWS_ALERT_WEBHOOK_URL`(Teams/Slack 호환
  `{"text": ...}`)로 제목+링크만 보낸다(최대 20건). 값이 없으면 조용히 건너뛴다. 목록이 비어 있던 첫 실행은
  밀린 기사 전체라서 알리지 않는다.
- 하루 요약: `alert: daily` 키워드로 지난 24시간에 찾은 기사의 제목·링크·출처·시간.
- 화면: 저장 목록을 5분 캐시로 읽고(R2에서 받은 파일을 해시 확인하며 임시 파일로 풀어 읽음), "자동 수집 상태"
  (마지막 자동 확인 시각, 확인 못 한 키워드, 2시간 넘게 멈추면 경고)를 보여 준다. "새 기사 확인" 버튼은 그대로
  있고 결과는 이 세션에만 더해진다(앱은 기사 목록을 쓰지 않음). 상태 저장이 거부되면(읽기 전용 키) 그 뒤로는
  세션 안에서만 유지하고 화면에 그렇게 적는다. R2도 로컬 파일도 없으면 Phase 1과 똑같이 동작한다.
- 모든 표시 시각은 한국 시간(Asia/Seoul)이다. 운영 서버는 UTC라서 `astimezone()`만 쓰면 9시간 어긋난다.
- PostgreSQL 테이블(`news_item` 등)은 그대로 두었지만 이번 단계에서는 쓰지 않는다.

### 로컬에서 R2 없이 확인

```bash
export PYTHONPATH=src
python -m purchase_price.scripts.collect_news_radar --output .local/news-radar.json.gz --no-alert
python -m purchase_price.scripts.collect_news_radar --mode digest --output .local/news-radar.json.gz
NEWS_RADAR_INDEX_PATH=.local/news-radar.json.gz streamlit run Home.py   # /news-radar
```

상태는 `.local/news-radar-status.json`, 하루 요약은 `.local/news-radar-digest/`에 생긴다.

### 운영 설정 (사람이 할 일)

- GitHub 저장소 Secrets: `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` (기존 R2 쓰기 Secrets 재사용),
  선택 `NEWS_ALERT_WEBHOOK_URL`.
- 앱에서 상태를 저장하려면 앱의 R2 키가 `news/v1/status.json`에 쓸 수 있어야 한다. 지금 운영 앱 키는 읽기
  전용이라 상태는 세션 안에서만 유지된다.

## 다음 단계 (기획서 Phase 2~3)

1. News Radar: ~~서버 저장 + 정기 수집 Job + 알림~~ Phase 2에서 R2로 완료. 남은 것: 상태 저장용 쓰기 권한 결정, 메일 발송.
2. Benchmark: KHIDI 회계정보공시 적재기 → `hospital_financial`; 심평원 병원정보 API로 병상수·종별 확정;
   회계기간 불일치 경고 표시; 5년 추이 그래프.
3. ALIO(국립대병원) 추가 연계, AI 설명 레이어(계산 결과만 입력).
