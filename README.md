# price-check-assistant

공개된 외부 가격자료를 수집·정리해 구매 담당자의 시장가격 검토를 보조하는 공개 PoC입니다. 1차 적용 맥락은 병원 관리부 구매업무이며, 향후 내부 이식을 고려한 구조로 설계합니다.

> 현재 버전은 **초기 PoC(v0.1)** 입니다. 첫 실제 Source로 조달청 나라장터쇼핑몰 `특정품목조달내역` API를 live 검증했고, `DATA_GO_KR_SERVICE_KEY`가 설정된 환경에서는 **exact model + verified G2B mapping**에 한해 Streamlit 통합검색에서도 실제 구매실적을 조회합니다. 검증되지 않은 품목분류는 자동 추정하지 않습니다.

## 현재 구현 상태

### 실제 나라장터 Source

- data.go.kr 서비스키를 이용한 실제 API 인증/호출 검증
- `getSpcifyPrdlstPrcureInfoList` 검색 파라미터와 핵심 응답필드 live 검증
- 단가·수량·금액·물품식별명·업체·수요기관·납품조건 수집
- `totalCount` 기반 페이지네이션과 `max_pages` 안전상한
- page safety cap 초과 시 날짜구간을 자동 이분할하는 adaptive collection
- 1일 구간도 page cap을 초과하면 부분 결과를 성공으로 제시하지 않고 fail-closed
- 원문 `raw_evidence` 저장 및 SHA-256 중복수집 방지 경로
- item-level G2B external key와 가격관측 provenance/derivation version 관리
- API 오류 envelope 및 Secret 비노출 처리
- 외부 API에 의존하지 않는 fixture CI

### 사용자 통합검색의 G2B 동작

통합검색에서 G2B 자동조회는 다음 조건을 모두 만족할 때만 실행합니다.

1. 로컬 또는 deployment 환경에 `DATA_GO_KR_SERVICE_KEY`가 설정돼 있음
2. 사용자가 모델명을 입력함
3. 해당 exact model이 `data/g2b_product_mappings.csv`에서 `verified` 상태임

사용자는 최근 30/90/180/365일 중 검색기간을 선택할 수 있습니다. 서비스키가 없거나 mapping이 미검증이면 G2B를 추정 호출하지 않고 제조사 공개가격 collector만 계속 동작합니다.

G2B 실적가격도 현재는 VAT·배송·설치·옵션·보증 등 거래조건이 완전히 구조화되지 않았으므로 `ComparisonScope.OBSERVED_ONLY`입니다. 즉 실제 구매실적 숫자를 찾더라도 현재 견적과 조건동등성이 검증되기 전에는 **견적이 높다/낮다 판정에 사용하지 않습니다.**

### Phase 0 G2B 매핑

`data/g2b_product_mappings.csv`에서 20개 benchmark의 나라장터 표준 세부품명 매핑 상태를 관리합니다.

현재 자동 검색에 사용할 수 있도록 검증된 매핑은 다음 4개입니다.

| 모델 | G2B 세부품명 | 세부품명번호 |
| --- | --- | --- |
| Sophie | 인공호흡기 | 4227220901 |
| NT960XJG-K72AG | 노트북컴퓨터 | 4321150301 |
| ApeosPrint C5570 GK | 레이저프린터 | 4321210501 |
| ThinkStation P2 Tower | 워크스테이션 | 4321151501 |

나머지 품목은 `unverified`입니다. 매핑이 불명확하면 검색어를 임의 생성하지 않고 G2B 자동검색을 건너뜁니다.

### 가격판정에서 하지 않는 것

- 후보 모델 토큰이 일치했다는 이유만으로 동일제품으로 확정하지 않음
- F3 매칭 전 나라장터 가격은 `MatchGrade.X` 유지
- X 가격을 관측 직접가격 범위 A/B 계산에 포함하지 않음
- A/B라도 예산·기초금액 등 직접가격이 아닌 Evidence Type은 가격범위에서 제외
- A/B + 직접가격이어도 비KRW·비정상 금액은 KRW 관측범위에서 제외
- VAT·단위·배송·설치·옵션·보증 등 조건이 확인되지 않은 `observed_only` 근거로 견적 고저를 판정하지 않음
- 반복 거래건수를 독립 출처 여러 개처럼 계산하지 않음
- 최저가를 적정가격 또는 구매권고로 자동 판단하지 않음
- 실제 본원 구매단가·견적서·계약자료를 공개 저장소에 저장하지 않음

자세한 나라장터 구현계약은 `docs/F1_G2B_SHOPPING.md`, 사용자 검색 계약은 `docs/PHASE1_G2B_USER_SEARCH.md`를 참고하세요.

## 공개 저장소 운영 경계

이 저장소는 초기 PoC 단계에서 **Public**으로 운영합니다. 따라서 다음 자료는 커밋하지 않습니다.

- 실제 본원 구매단가 및 거래업체별 계약단가
- 실제 업체 견적서 원본 및 내부 결재문서
- 개인정보·병원 내부정보가 포함된 파일
- API 키, 비밀번호, 토큰 등 secret

공개 저장소에는 공개정보, 샘플 데이터, 비식별 테스트 자료만 포함합니다. 실제 내부자료 연계는 별도 승인 후 비공개/내부 환경에서 수행합니다.

## 기술 스택

- Python 3.11+
- Streamlit
- PostgreSQL 16
- SQLAlchemy 2
- Alembic
- pytest / Ruff

## 로컬 개발환경 설치

### 사전 준비

- Python 3.11 이상 (필수)
- Git (필수)
- Docker Desktop 또는 로컬 PostgreSQL 16 (선택)

**PostgreSQL은 선택입니다.** 테스트, Ruff, 매칭 benchmark, 대부분의 코드작업은 DB 없이 동작합니다.
DB는 저장된 가격관측값을 읽거나 수집 결과를 영구 적재할 때 필요합니다.
Docker가 없으면 설치 스크립트는 DB 단계만 건너뛰고 나머지를 끝까지 진행합니다.

### Windows

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup.ps1     # venv, 패키지, .env, (가능하면) DB + migration, 환경점검
.\scripts\test.ps1      # CI와 동일한 검사
.\scripts\run.ps1       # Streamlit 실행
```

### Linux / macOS

```bash
./scripts/setup.sh
./scripts/test.sh
./scripts/run.sh
```

### 환경 점검

설치가 끝나면 언제든 다음으로 현재 상태를 확인할 수 있습니다.

```bash
python -m purchase_price.scripts.doctor
```

Python 버전, 패키지 설치, 개발도구, 데이터 registry는 **필수** 항목이라 실패하면 exit 1입니다.
`.env`, DB 연결, migration 적용상태, `DATA_GO_KR_SERVICE_KEY`는 **선택** 항목이라 없으면 `SKIP`으로만 표시하고 `doctor_status=ready`로 끝납니다. `.env`가 없어도 Settings 기본값과 프로세스 환경변수로 동작하며, CI가 실제로 그렇게 전체 테스트를 실행합니다. 선택 항목까지 모두 갖춰졌는지 확인하려면 `--strict`를 붙입니다. 서비스키는 존재 여부만 출력하며 값은 절대 출력하지 않습니다.

### 수동 설치

```bash
python3 -m venv .venv && . .venv/bin/activate     # Windows: py -3.11 -m venv .venv
pip install -U pip && pip install -e ".[dev]"
cp .env.example .env
docker compose up -d db                            # 선택. 로컬 PostgreSQL 16을 써도 됩니다
python -m purchase_price.scripts.init_db           # DB가 있을 때만
python -m purchase_price.scripts.doctor
```

실제 나라장터 live 호출이 필요할 때만 로컬 `.env`에 서비스키를 넣습니다. 실제 키는 Git에 커밋하지 않습니다.

```text
DATA_GO_KR_SERVICE_KEY=...
```

Streamlit은 `streamlit run Home.py`로 실행하며 브라우저에서 보통 `http://localhost:8501`이 열립니다.

## 검색 동작

통합검색의 기본 사용자 surface에는 개발용 mock 가격이 포함되지 않습니다. `MockPublicCollector`는 테스트/개발에서 `include_mock=True`로 명시한 경우에만 활성화됩니다.

실제 G2B 사용자 검색은 모든 품목을 포괄하는 generic 검색기가 아니라 **검증된 exact model mapping**에 대한 보수적 검색입니다. 현재 verified 4개 모델 외 품목은 mapping 근거를 추가하기 전까지 G2B 자동조회 대상이 아닙니다.

## 테스트

```bash
./scripts/test.sh          # Windows: .\scripts\test.ps1
```

이 스크립트는 CI와 같은 순서로 Ruff, pytest, 매칭 benchmark를 실행하므로 로컬에서 통과하면 PR도 통과합니다.
개별 실행은 다음과 같습니다.

```bash
ruff check .
pytest -q
python -m purchase_price.scripts.evaluate_match_benchmark --fail-on-mismatch
alembic check              # DB가 있을 때. ORM 모델과 migration 불일치 검출
```

일반 CI는 GitHub Secret이나 외부 API를 호출하지 않습니다. CI는 `evaluate_match_benchmark --fail-on-mismatch`로 사람 판정 Ground Truth와 matcher 결과가 하나라도 다르면 실패합니다. 실제 API 호출은 `.github/workflows/g2b-live-smoke.yml`과 `.github/workflows/g2b-ground-truth-capture.yml`을 수동 실행할 때만 수행합니다.

따라서 일반 CI green은 코드·fixture·회귀 검증을 의미하며, **실제 user-surface G2B live 성공을 의미하지 않습니다.** 실제키 환경의 smoke 검증은 별도로 기록합니다.

## 구조

```text
Home.py / pages/                         Streamlit UI
src/purchase_price/clients               공공 API 공통 transport
src/purchase_price/collectors            외부 데이터 Source adapter
src/purchase_price/services              매핑·수집·제품매칭·가격분석 규칙
src/purchase_price/repositories          PostgreSQL 접근 / raw evidence
data/phase0_products.csv                  Phase 0 benchmark 20개
data/g2b_product_mappings.csv             검증된 G2B 세부품명 mapping registry
scripts/                                 로컬 설치·검사·실행 스크립트
docs/                                    설계·구현계약·다음 구현순서
tests/                                   핵심 규칙/fixture 테스트
```

## 보안 원칙

- 실제 본원 구매단가를 공개 PoC에 저장하지 않습니다.
- 실제 견적서 업로드는 내부 승인 전 영구 저장하지 않는 구조를 기본값으로 합니다.
- API 키/비밀번호는 `.env` 또는 GitHub/deployment secret으로 관리하고 Git에 커밋하지 않습니다.

## 다음 작업

1. 나머지 Phase 0 benchmark의 G2B 표준 세부품명/번호를 공개근거 기반으로 확대합니다. 다만 조사 결과 병원 의료장비 상당수가 나라장터에 존재하지 않아 G2B만으로는 coverage 상한이 있습니다 ([조사 결과](docs/PHASE1_G2B_MAPPING_COVERAGE.md)).
2. G2B 계약정보서비스를 추가해 쇼핑몰 구매실적과 독립된 공공계약 근거를 확보합니다.
3. VAT·단위·배송·설치·옵션·보증을 구조화하고 검증된 경우에만 `quote_comparable`로 승격합니다.

제품군 문자열 부분일치만으로 C등급을 부여하던 문제는 정규화 exact equality 요구로 처리했습니다.
자세한 계약은 [docs/F3_PRODUCT_MATCHING.md](docs/F3_PRODUCT_MATCHING.md)를 참고하세요.
