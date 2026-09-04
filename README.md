# price-check-assistant

공개된 외부 가격자료를 수집·정리해 구매 담당자의 시장가격 검토를 보조하는 공개 PoC입니다. 1차 적용 맥락은 병원 관리부 구매업무이며, 향후 내부 이식을 고려한 구조로 설계합니다.

> 현재 버전은 **Controlled UAT 단계의 공개 PoC**입니다. 조달청 나라장터쇼핑몰·계약정보, 제조사 공개가격, 견적서 구조추출, 식약처 의료기기 identity/공급사 조사까지 연결되어 있습니다. 공개근거가 부족하거나 조건동등성이 확인되지 않으면 가격을 생성하거나 견적의 높고 낮음을 자동 판정하지 않습니다.

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
- 나라장터 계약정보 `getCntrctInfoListThngPPSSrch` 기반 계약번호·기관·방법·상세원문 조회

### 사용자 통합검색의 G2B 동작

통합검색에서 G2B 자동조회는 다음 조건을 모두 만족할 때만 실행합니다.

1. 로컬 또는 deployment 환경에 `G2B_SERVICE_KEY` 또는 하위호환 `DATA_GO_KR_SERVICE_KEY`가 설정돼 있음
2. 사용자가 모델명을 입력함
3. 해당 exact model이 `data/g2b_product_mappings.csv`에서 `verified` 상태임

사용자는 최근 30/90/180/365일 중 검색기간을 선택할 수 있습니다. 서비스키가 없거나 mapping이 미검증이면 G2B를 추정 호출하지 않고 다른 연결 source만 계속 동작합니다.

G2B 실적가격은 실제 관측가격으로 사용할 수 있지만, 현재 견적과 VAT·수량/단위·배송·설치·옵션·보증·유지보수 등 거래조건이 검증되지 않은 근거는 `ComparisonScope.OBSERVED_ONLY`입니다. 즉 실제 구매실적 숫자를 찾더라도 조건동등성이 확인되기 전에는 **견적이 높다/낮다 판정에 사용하지 않습니다.**

### Phase 0 G2B 매핑

`data/g2b_product_mappings.csv`에서 20개 benchmark의 나라장터 표준 세부품명 매핑 상태를 관리합니다.

현재 자동 검색에 사용할 수 있도록 검증된 G2B 매핑은 다음 5개입니다.

| 모델 | G2B 세부품명 | 세부품명번호 |
| --- | --- | --- |
| Sophie | 인공호흡기 | 4227220901 |
| Veriti Pro Dx | 유전자증폭기 | 4110630701 |
| NT960XJG-K72AG | 노트북컴퓨터 | 4321150301 |
| ApeosPrint C5570 GK | 레이저프린터 | 4321210501 |
| ThinkStation P2 Tower | 워크스테이션 | 4321151501 |

나머지 품목은 `unverified`입니다. 매핑이 불명확하면 검색어·분류를 임의 생성하지 않고 G2B 자동검색을 건너뜁니다. 나라장터에 병원 의료장비의 exact 거래가 존재하지 않는 경우가 많으므로 mapping 수 자체를 성과목표로 삼지 않습니다.

### 견적서 및 가격조건

- `.xlsx/.xls` 견적서의 품목·제조사·모델·규격·수량·단가·총액 추출
- text PDF 견적 추출, 스캔 PDF는 fail-closed
- VAT·배송·설치·옵션·보증·유지보수·기타 상업조건의 명시값 추출
- 견적조건 ↔ 외부 가격조건을 `match / conflict / unknown`으로 대조
- 보수적인 `quote_comparable` **후보** 게이트
- 거래일/수집·검증일 기준 evidence freshness 표시

후보 게이트 통과만으로 `ComparisonScope.QUOTE_COMPARABLE`로 자동 승격하지 않습니다. 다음 단계는 담당자가 원문과 조건을 확인한 현재 검토 pair에 한해 명시적으로 승인하는 workflow입니다.

### 의료기기 조사

- 식약처 공식 품목 조회 후 exact 모델 identity 확인
- ambiguous / 취소·취하 / 수출전용 fail-closed
- 동일 공식 품목의 국내 정상 등록모델을 경쟁장비 후보로 제시
- 정상 동일품목 후보가 0건일 때만 broad 결과를 `추가 조사 후보`로 표시
- 공급사 우선순위: G2B 실제 납품업체 → MFDS 업허가 업체 → 웹 후보
- UDI-DI를 알고 있을 때 exact lookup
- Safety는 exact 모델/허가번호 확인키와 공식 수동 확인 경로 제공

회수·판매중지 자동 adapter와 모델명→UDI 역검색은 공식 operation/request contract를 확보하기 전까지 추정 구현하지 않습니다.

### 가격판정에서 하지 않는 것

- 후보 모델 토큰이 일치했다는 이유만으로 동일제품으로 확정하지 않음
- 모델·제조사·명백한 핵심규격 충돌을 직접 비교로 승격하지 않음
- X 가격을 관측 직접가격 범위 A/B 계산에 포함하지 않음
- A/B라도 예산·기초금액·계약총액 등 직접가격이 아닌 Evidence Type은 가격범위에서 제외
- A/B + 직접가격이어도 비KRW·비정상 금액은 KRW 관측범위에서 제외
- `observed_only` 근거로 견적 고저를 판정하지 않음
- candidate gate 통과만으로 `quote_comparable` 자동 승격하지 않음
- 반복 거래건수를 독립 출처 여러 개처럼 계산하지 않음
- 최저가를 적정가격 또는 구매권고로 자동 판단하지 않음
- 실제 본원 구매단가·견적서·계약자료를 공개 저장소에 저장하지 않음

자세한 구현상태는 `docs/V2_IMPLEMENTATION_STATUS.md`, 다음 순서는 `docs/NEXT_IMPLEMENTATION.md`를 참고하세요.

## 공개 저장소 운영 경계

이 저장소는 Public PoC로 운영합니다. 따라서 다음 자료는 커밋하지 않습니다.

- 실제 본원 구매단가 및 거래업체별 계약단가
- 실제 업체 견적서 원본 및 내부 결재문서
- 개인정보·병원 내부정보가 포함된 파일
- API 키, 비밀번호, 토큰 등 secret

공개 저장소에는 공개정보, 샘플 데이터, 비식별·사용승인이 명확한 테스트 자료만 포함합니다. 실제 내부자료 연계는 별도 승인 후 비공개/내부 환경에서 수행합니다.

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

**PostgreSQL은 선택입니다.** 테스트, Ruff, 매칭 benchmark, 대부분의 코드작업은 DB 없이 동작합니다. DB는 저장된 가격관측값을 읽거나 수집 결과를 영구 적재할 때 필요합니다.

### Windows

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup.ps1
.\scripts\test.ps1
.\scripts\run.ps1
```

### Linux / macOS

```bash
./scripts/setup.sh
./scripts/test.sh
./scripts/run.sh
```

### 환경 점검

```bash
python -m purchase_price.scripts.doctor
```

Python 버전, 패키지 설치, 개발도구, 데이터 registry는 필수 점검입니다. `.env`, DB, migration, 외부 API service key는 선택 항목이며 없는 경우 `SKIP`으로 표시합니다. 서비스키는 존재 여부만 출력하며 값은 출력하지 않습니다.

### 수동 설치

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -U pip && pip install -e ".[dev]"
cp .env.example .env
docker compose up -d db                            # 선택
python -m purchase_price.scripts.init_db           # DB가 있을 때만
python -m purchase_price.scripts.doctor
```

source별 service key는 로컬 `.env`, GitHub Secret 또는 Streamlit Secrets에만 둡니다.

```text
G2B_SERVICE_KEY=...
MFDS_SERVICE_KEY=...
# legacy fallback이 필요한 경우에만
DATA_GO_KR_SERVICE_KEY=...
```

Streamlit은 `streamlit run Home.py`로 실행합니다.

## 검색 동작

통합검색의 기본 사용자 surface에는 개발용 mock 가격이 포함되지 않습니다. `MockPublicCollector`는 테스트/개발에서 `include_mock=True`로 명시한 경우에만 활성화됩니다.

실제 G2B 사용자 검색은 모든 품목을 포괄하는 generic 검색기가 아니라 **검증된 exact model mapping**에 대한 보수적 검색입니다. 현재 verified 5개 모델 외 품목은 mapping 근거를 추가하기 전까지 G2B 자동조회 대상이 아닙니다.

## 테스트

```bash
./scripts/test.sh          # Windows: .\scripts\test.ps1
```

일반 CI는 다음 안전게이트를 실행합니다.

```bash
ruff check .
pytest -q
python -m purchase_price.scripts.evaluate_match_benchmark --fail-on-mismatch
python -m purchase_price.scripts.run_phase0_validation --offline ...
```

일반 CI는 GitHub Secret이나 외부 API를 호출하지 않습니다. 따라서 CI green은 코드·fixture·AppTest·benchmark·offline integration 회귀검증을 의미하며, **실제 live API 성공을 의미하지 않습니다.** live smoke는 수동 workflow와 실제 배포환경에서 별도로 기록합니다.

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
tests/                                   핵심 규칙/fixture/AppTest
```

## 다음 작업

1. **공개근거 provenance 일관화 마무리** — G2B 계약정보 public allow-list, canonical payload, SHA-256, source record/URL, normalized record 연결. PR #53에서 검증 중이며 승인 전 merge하지 않습니다.
2. **Controlled UAT** — 일반 전산제품·병원 비품·의료장비·다품목 Excel·text PDF·조건 상세/부족·정확/부정확 모델·명백한 규격충돌을 비식별 샘플로 검증합니다.
3. **담당자 승인형 비교가능성 workflow** — candidate gate → 원문/조건 확인 → 현재 session의 견적-근거 pair만 명시적으로 `QUOTE_COMPARABLE` 승인 → `assess_prices` 실행. 자동승격과 영구 source 변경은 금지합니다.
4. **Live smoke** — G2B Shopping/계약, MFDS 품목/업체, UDI-DI, 실제 Streamlit 검색을 CI와 분리해 확인합니다.
5. **Source coverage 확대** — 제조사 공식 공개가격·검증 가능한 공공계약·신뢰 가능한 B2B/유통 source 순서로 확대합니다.
6. 기능과 UAT가 안정화된 뒤 **single-screen 구매검토 UI**로 통합합니다.

Safety 자동 API와 모델명→UDI 역검색은 공식 request contract 확보 즉시 별도 구현합니다. 내부 구매단가 연계와 진료재료는 Public PoC의 업무효과가 확인되고 내부 승인을 받은 뒤 진행합니다.
