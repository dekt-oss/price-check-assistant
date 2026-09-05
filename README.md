# price-check-assistant

공개된 외부 가격자료를 수집·정리해 구매 담당자의 시장가격 검토를 보조하는 공개 PoC입니다. 1차 적용 맥락은 병원 관리부 구매업무이며, 향후 내부 이식을 고려한 구조로 설계합니다.

> 현재 버전은 **Controlled pre-UAT를 통과하고 실제 live/업무 UAT를 준비하는 공개 PoC**입니다. 조달청 나라장터 Shopping·계약정보, 제조사 공개가격, 견적서 Excel/PDF/OCR 구조추출, 식약처 의료기기 identity/업체 조사, 담당자 승인형 가격비교까지 연결되어 있습니다. 공개근거가 부족하거나 조건동등성이 확인되지 않으면 가격을 생성하거나 견적의 높고 낮음을 자동 판정하지 않습니다.

## 현재 구현 상태

### 나라장터 Shopping / 납품가격

- data.go.kr 기반 G2B Shopping adapter
- verified exact-model mapping에 한해서만 자동검색
- 세부품명번호 exact filter
- 단가·수량·금액·물품식별명·업체·수요기관·납품조건 수집
- `totalCount` pagination + `max_pages` 안전상한
- page safety cap 초과 시 날짜구간 adaptive partition
- 1일 구간도 page cap을 초과하면 부분결과를 성공으로 제시하지 않고 fail-closed
- raw evidence / SHA-256 dedupe / provenance 경로
- API 오류 envelope와 정상 0건 분리
- serviceKey URL/error/log redaction

통합검색에서 G2B 자동조회는 다음 조건을 모두 만족할 때만 실행합니다.

1. 다음 우선순위 중 하나의 service key가 설정됨
   - `G2B_SERVICE_KEY`
   - `DATA_GO_KR_MARKET_SERVICE_KEY`
   - legacy `DATA_GO_KR_SERVICE_KEY`
2. 사용자가 모델명을 입력함
3. 해당 exact model이 `data/g2b_product_mappings.csv`에서 `verified` 상태임

현재 verified mapping은 5개입니다.

| 모델 | G2B 세부품명 | 세부품명번호 |
| --- | --- | --- |
| Sophie | 인공호흡기 | 4227220901 |
| Veriti Pro Dx | 유전자증폭기 | 4110630701 |
| NT960XJG-K72AG | 노트북컴퓨터 | 4321150301 |
| ApeosPrint C5570 GK | 레이저프린터 | 4321210501 |
| ThinkStation P2 Tower | 워크스테이션 | 4321151501 |

나머지 품목은 `unverified`입니다. 매핑이 불명확하면 검색어·분류를 임의 생성하지 않고 G2B 자동검색을 건너뜁니다.

G2B 실적가격은 실제 관측가격으로 사용할 수 있지만 VAT·수량/단위·배송·설치·옵션·보증·유지보수 등 조건동등성이 확인되지 않은 근거는 `ComparisonScope.OBSERVED_ONLY`입니다. 실제 구매실적 숫자를 찾았다는 이유만으로 현재 견적이 높다/낮다고 판정하지 않습니다.

### 나라장터 계약정보 provenance

- `getCntrctInfoListThngPPSSrch` 기반 계약번호·기관·방법·상세근거 조회
- 계약총액은 제품 단가로 환산하지 않음
- public response allow-list
- recursive secret-like field 차단
- canonical JSON
- SHA-256 fingerprint
- source record / URL / normalized Evidence 연결
- UI fingerprint 표시

### 견적서 구조추출

지원:

- `.xlsx`
- `.xls`
- text-layer PDF
- scan/image-only PDF 로컬 OCR

PDF 추출은 가능한 구조를 우선 사용합니다.

```text
ruled table
→ word X/Y geometry
→ text fallback
→ text layer가 없으면 local OCR
```

스캔 PDF OCR:

- `pypdfium2`로 PDF rasterize
- 로컬 Tesseract `kor+eng`
- 최대 앞 12페이지 안전상한
- 외부 Vision API로 견적 원문 전송하지 않음
- OCR 결과도 반드시 담당자 원문 확인 대상

GitHub Actions에서는 실제 Ubuntu Tesseract와 `kor`/`eng` language pack을 설치하고, 실제 image-only synthetic PDF를 `extract_quote_file()`까지 통과시키는 E2E를 실행합니다.

이 검증은 실제 공급사 스캔 견적의 OCR 정확도를 증명하는 것은 아닙니다. 실제 견적 UAT가 별도로 필요합니다.

### 견적 상업조건 / 비교가능성

구조화 대상:

- VAT
- 수량 / 단위
- 배송
- 설치
- 옵션
- 보증
- 유지보수
- 기타 조건
- 기준일

견적조건과 외부근거 조건을 `match / conflict / unknown`으로 대조합니다.

`quote_comparable` candidate gate는 보수적으로 동작합니다. candidate 통과만으로 직접 비교 승인을 만들지 않습니다.

```text
candidate gate
→ 담당자 원문/조건 확인
→ 현재 session의 quote/evidence pair 명시적 승인
→ 해당 pair만 QUOTE_COMPARABLE
→ assess_prices
```

승인은 pair SHA-256으로 현재 견적/근거 쌍에만 묶이고, 원본 public Evidence의 `comparison_scope`는 변경하지 않습니다. candidate 실패를 사람 승인으로 우회할 수 없습니다.

### 의료기기 조사

- 식약처 공식 품목명 조회
- 응답 안에서 exact 모델 identity local match
- ambiguous permit fail-closed
- 취소·취하 / 수출전용 자동승격 금지
- 동일 공식 품목의 국내 정상 등록모델을 경쟁장비 후보로 제시
- G2B 실제 납품업체 → MFDS 업허가 업체 → 웹 후보 공급사 우선순위
- UDI-DI를 알고 있을 때 exact lookup
- Safety 공식 수동 확인 경로 제공

업체 업허가 상태를 제조사 공식 총판으로 의미확장하지 않습니다.

회수·판매중지 자동 adapter와 모델명→UDI 역검색은 공식 operation/request contract를 확보하기 전까지 추정 구현하지 않습니다.

### 가격판정에서 하지 않는 것

- 후보 모델 토큰만 일치했다고 동일제품 확정
- 모델·제조사·명백한 핵심규격 충돌을 직접 비교로 승격
- C/D/X를 A/B 직접가격 범위에 포함
- 예산·기초금액·계약총액을 제품 단가로 사용
- 비KRW·비정상 금액을 KRW 직접 관측범위에 포함
- `observed_only` 근거로 견적 고저 판정
- candidate gate 통과만으로 `QUOTE_COMPARABLE` 자동승격
- 반복 거래건수를 독립 source 여러 개처럼 계산
- 최저가를 적정가격 또는 구매권고로 자동판단
- 실제 본원 구매단가·견적서·계약자료를 공개 저장소에 저장

## Shared data.go.kr key 계약

애플리케이션과 live workflow의 key 우선순위:

```text
source-specific key
→ DATA_GO_KR_MARKET_SERVICE_KEY
→ legacy DATA_GO_KR_SERVICE_KEY
```

G2B:

```text
G2B_SERVICE_KEY
→ DATA_GO_KR_MARKET_SERVICE_KEY
→ DATA_GO_KR_SERVICE_KEY
```

MFDS:

```text
MFDS_SERVICE_KEY
→ DATA_GO_KR_MARKET_SERVICE_KEY
→ DATA_GO_KR_SERVICE_KEY
```

여러 승인 API가 같은 data.go.kr 발급키를 사용할 수 있는 환경에서는 `DATA_GO_KR_MARKET_SERVICE_KEY`를 공통 fallback으로 사용할 수 있습니다. 실제 secret 값은 저장소·로그·artifact에 기록하지 않습니다.

Streamlit Community Cloud App Secrets와 GitHub Actions Repository Secrets는 서로 별도 secret store입니다.

## Live validation

일반 CI는 외부 API를 자동 호출하지 않습니다. Live workflow는 모두 `workflow_dispatch` 수동 실행만 허용합니다.

현재 제공되는 주요 workflow:

- G2B Live Smoke
- G2B Ground Truth Capture
- Phase 0 Live Validation
- MFDS Live Validation

상세 실행계약은 `docs/LIVE_UAT_RUNBOOK.md`를 참고하세요.

Live 결과는 반드시 다음을 구분합니다.

```text
성공 N건
정상 0건
실패
미검증
```

CI green은 실제 G2B/MFDS API 또는 Production Streamlit 성공을 의미하지 않습니다.

## 실제 견적 UAT

`pages/13_견적추출_UAT.py`는 실제/승인된 견적을 Public repo에 저장하지 않고 현재 세션에서 원문 대조할 수 있는 UAT 화면입니다.

주요 지표:

- extraction success/failure
- extraction strategy
- parser 처리시간
- 담당자 원문대조 시간
- expected / actual / matched item count
- 품목 false positive(FP)
- 품목 false negative(FN)
- item precision / recall
- 필드 오류율
- OCR / text PDF / Excel 전략별 집계

한 품목의 누락/추가가 뒤 모든 행의 필드오류로 연쇄 계산되지 않도록 순서보존 row alignment를 사용합니다. 이 alignment는 UAT 측정용이며 생산 identity/가격판정 규칙과 무관합니다.

다운로드 UAT JSON에는 실제 파일명·견적 원문·제품명·제조사·모델·규격·단가·총액을 넣지 않습니다.

1차 실제 표본 목표는 서로 다른 양식 **최소 5건**입니다.

## 공개 저장소 운영 경계

이 저장소에 커밋하지 않습니다.

- 실제 본원 구매단가 및 거래업체별 계약단가
- 실제 업체 견적서 원본 및 내부 결재문서
- 개인정보·병원 내부정보가 포함된 파일
- API key, 비밀번호, token 등 secret

공개 저장소에는 공개정보, synthetic/sample 데이터, 비식별·사용승인이 명확한 테스트 자료만 포함합니다.

## 기술 스택

- Python 3.11+
- Streamlit
- PostgreSQL 16
- SQLAlchemy 2 / Alembic
- pandas / openpyxl / xlrd
- pdfplumber / pypdf
- pypdfium2 / Tesseract / pytesseract
- pytest / Ruff

## 로컬 개발환경 설치

### 사전 준비

- Python 3.11 이상
- Git
- Docker Desktop 또는 PostgreSQL 16은 선택
- scan PDF OCR을 사용할 경우 Tesseract + `kor`/`eng` language pack

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

### 수동 설치

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"
cp .env.example .env
```

DB가 필요할 때만:

```bash
docker compose up -d db
python -m purchase_price.scripts.init_db
```

환경 점검:

```bash
python -m purchase_price.scripts.doctor
```

Secret은 로컬 `.env`, GitHub Actions Secret, Streamlit App Secrets에만 둡니다.

```text
DATA_GO_KR_MARKET_SERVICE_KEY=...
# source-specific override가 필요할 때만
G2B_SERVICE_KEY=...
MFDS_SERVICE_KEY=...
# legacy compatibility가 필요할 때만
DATA_GO_KR_SERVICE_KEY=...
```

Streamlit:

```bash
streamlit run Home.py
```

## 테스트 / CI

일반 CI는 다음 gate를 실행합니다.

```text
Ruff
→ Tesseract system package / kor / eng 확인
→ Streamlit 전체 page startup smoke
→ pytest (real PDF + real OCR synthetic E2E 포함)
→ Match benchmark
→ Phase0 offline integration
→ Controlled UAT deterministic offline gate
→ artifact upload
```

Controlled UAT는 현재 15개 protocol 중 12개를 offline 자동 실행하고, live-required 3개는 실제 외부 API 검증으로 남겨둡니다.

Known synthetic comparison FN 1건(UAT-11 quantity mismatch)이 있으나 이 한 건을 근거로 quantity equality를 완화하지 않습니다.

## 현재 단계 / 다음 작업

상세 로드맵은 `docs/NEXT_IMPLEMENTATION.md`, v2 대비 상태는 `docs/V2_IMPLEMENTATION_STATUS.md`를 기준으로 합니다.

현재 순서:

```text
actual live smoke
→ 실제 견적 최소 5건 UAT
→ 전체 구매검토 UAT
→ 발견 결함 보정
→ 필요 시 source coverage 확대
→ single-screen UI
→ 내부 이식 검토
```

현재 목표는 기능 수를 늘리는 것이 아니라 **잘못된 직접비교를 하지 않으면서 실제 구매검토 시간을 줄이는지 증명하는 것**입니다.
