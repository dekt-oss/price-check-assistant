# price-check-assistant

공개된 외부 가격자료를 수집·정리해 구매 담당자의 시장가격 검토를 보조하는 공개 PoC입니다. 1차 적용 맥락은 병원 관리부 구매업무이며, 향후 내부 이식을 고려한 구조로 설계합니다.

> 현재 버전은 **초기 PoC(v0.1)** 입니다. 첫 실제 Source로 조달청 나라장터쇼핑몰 `특정품목조달내역` API 수집 경로를 live 검증했습니다. 다만 모든 제품의 일반 검색과 동일제품 A/B 판정은 아직 구현 중이며, 검증되지 않은 품목분류는 자동 추정하지 않습니다.

## 현재 구현 상태

### 실제 나라장터 Source

- data.go.kr 서비스키를 이용한 실제 API 인증/호출 검증
- `getSpcifyPrdlstPrcureInfoList` 검색 파라미터와 핵심 응답필드 live 검증
- 단가·수량·금액·물품식별명·업체·수요기관·납품조건 수집
- 페이지네이션과 `max_pages` 안전상한
- 원문 `raw_evidence` 저장 및 SHA-256 중복수집 방지
- API 오류 envelope 및 Secret 비노출 처리
- 외부 API에 의존하지 않는 fixture CI

### Phase 0 G2B 매핑

`data/g2b_product_mappings.csv`에서 20개 benchmark의 나라장터 표준 세부품명 매핑 상태를 관리합니다.

현재 자동 검색에 사용할 수 있도록 검증된 매핑은 다음 2개입니다.

| 모델 | G2B 세부품명 | 세부품명번호 |
| --- | --- | --- |
| Sophie | 인공호흡기 | 4227220901 |
| NT960XJG-K72AG | 노트북컴퓨터 | 4321150301 |

나머지 품목은 `unverified`입니다. 매핑이 불명확하면 검색어를 임의 생성하지 않고 실패하도록 설계했습니다.

### 아직 하지 않는 것

- 후보 모델 토큰이 일치했다는 이유만으로 동일제품으로 확정하지 않음
- F3 매칭 전 나라장터 가격은 `MatchGrade.X` 유지
- X 가격을 참고가격대 A/B 계산에 포함하지 않음
- 최저가를 적정가격 또는 구매권고로 자동 판단하지 않음
- 실제 본원 구매단가·견적서·계약자료를 공개 저장소에 저장하지 않음

자세한 나라장터 구현계약은 `docs/F1_G2B_SHOPPING.md`를 참고하세요.

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
DB는 Streamlit 화면에서 저장된 가격관측값을 읽거나 수집 결과를 적재할 때만 필요합니다.
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

Python 버전, 패키지 설치, 개발도구, `.env`, 데이터 registry는 **필수** 항목이라 실패하면 exit 1입니다.
DB 연결, migration 적용상태, `DATA_GO_KR_SERVICE_KEY`는 **선택** 항목이라 없으면 `SKIP`으로만 표시하고
`doctor_status=ready`로 끝납니다. 세 가지까지 모두 갖춰졌는지 확인하려면 `--strict`를 붙입니다.
서비스키는 존재 여부만 출력하며 값은 절대 출력하지 않습니다.

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

## 개발용 샘플 검색

통합검색에서 모델명에 `XYZ-100`을 입력하면 기존 개발용 가격관측값이 나타납니다. 이 값은 **실제 시장자료가 아닙니다.**

실제 G2B generic UI 검색은 아직 모든 품목에 연결하지 않았습니다. 현재 실제 Source 경로는 검증된 표준 세부품명 기반 collector/service 단계에 있습니다.

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

일반 CI는 GitHub Secret이나 외부 API를 호출하지 않습니다. CI는 `evaluate_match_benchmark --fail-on-mismatch`로
사람 판정 Ground Truth와 matcher 결과가 하나라도 다르면 실패합니다. 실제 API 호출은
`.github/workflows/g2b-live-smoke.yml`과 `.github/workflows/g2b-ground-truth-capture.yml`을 수동 실행할 때만 수행합니다.

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

1. 나머지 Phase 0 benchmark의 G2B 표준 세부품명/번호를 근거 기반으로 확대합니다.
2. F3에서 제조사·모델·사양·옵션을 판정해 `MatchGrade.X` 후보를 A/B/C/D/X로 분류합니다.
3. 제조사 공개가격·공공계약 등 나라장터 외 Source를 추가합니다.
4. 충분한 가격 Evidence가 확보된 뒤 Streamlit 통합검색에 실제 결과를 연결합니다.
