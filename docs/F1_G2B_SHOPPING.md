# F1 — 나라장터쇼핑몰 품목정보 Collector

## 목적

`조달청_나라장터쇼핑몰 품목정보 서비스`를 첫 실제 공공조달 가격 Source로 연결한다.

## 공식 서비스 계약

- REST, JSON+XML
- Base URL: `https://apis.data.go.kr/1230000/at/ShoppingMallPrdctInfoService`
- 개발/운영 자동승인
- 개발계정 기본 트래픽 1,000건
- 주요 operation
  - `getMASCntrctPrdctInfoList`
  - `getUcntrctPrdctInfoList`
  - `getThptyUcntrctPrdctInfoList`
  - `getDlvrReqInfoList`
  - `getDlvrReqDtlInfoList`
  - `getShoppingMallPrdctInfoList`
  - `getVntrPrdctOrderDealDtlsInfoList`
  - `getSpcifyPrdlstPrcureInfoList`
  - `getSpcifyPrdlstPrcureTotList`

F1 코드에서는 가격검토에 우선 필요한 4개 operation을 식별한다.

1. 쇼핑몰 품목 등록 내역
2. MAS 계약품목
3. 납품요구 상세
4. 특정품목 조달내역

## 2026-09-03 Live 검증 완료

GitHub Actions repository secret `DATA_GO_KR_SERVICE_KEY`를 사용해 실제 API 호출을 검증했다. Secret 값은 로그나 저장소에 노출하지 않는다.

### 인증/통신

- Secret 주입 확인
- API host 연결 확인
- Encoding/Decoding 서비스키를 한 번만 정규화하도록 공통 client 보강
- HTTP 4xx뿐 아니라 HTTP 200 안의 `OpenAPI_ServiceResponse` 오류 envelope도 실패 처리
- 서비스키/요청 URL을 오류 로그에 노출하지 않는 sanitized error 처리

### 특정품목조달내역 실응답

`getSpcifyPrdlstPrcureInfoList`에서 다음 파라미터 조합이 실제 정상 응답(`resultCode=00`)을 반환함을 확인했다.

- `pageNo`
- `numOfRows`
- `inqryDiv`
- `inqryBgnDate`
- `inqryEndDate`
- `inqryPrdctDiv`
- `fnlCntrctDlvrReqChgOrdYn`
- `dtilPrdctClsfcNoNm`

검증 fixture는 `tests/fixtures/g2b_shopping/specific_item_live_20260715.json`에 서비스키와 불필요 식별필드를 제거한 형태로 보존한다.

실응답에서 확인한 주요 필드:

- `prdctIdntNo`: 물품식별번호
- `prdctIdntNoNm`: 물품식별명/제품 식별 텍스트
- `prdctUprc`: 단가
- `prdctQty`: 수량
- `prdctUnit`: 단위
- `prdctAmt`: 금액
- `corpNm`: 업체명
- `cntrctDlvrReqNo`: 계약/납품요구 번호
- `cntrctDlvrDivNm`: 계약/납품요구 구분
- `cntrctDlvrReqDate`: 계약/납품요구 일자
- `uprcCntrctNo`: 단가계약번호
- `dminsttNm`: 수요기관
- `dlvryCndtnNm`: 납품조건

실제 검증 레코드에서는 `cntrctDlvrDivNm=납품요구`, `prdctUprc=450000`, `prdctQty=1`, `prdctAmt=450000`이 확인되었으며 parser는 이를 `DELIVERY_ORDER_UNIT_PRICE`로 분류한다.

## Fail-closed 가격 규칙

- `금액`/`prdctAmt`만으로 단가를 만들지 않는다.
- 특정품목 `단가`/`prdctUprc`는 `cntrctDlvrDivNm`의 계약/납품 의미가 확인될 때만 직접가격 EvidenceType으로 승격한다.
- F3 제품 매칭 전에는 모든 조달가격을 `MatchGrade.X`로 유지한다.
- 따라서 실제 단가가 수집되어도 동일제품 여부가 검증되기 전에는 참고가격대 계산에 들어가지 않는다.

## Raw evidence

API의 각 원문 record를 정규화 전에 `raw_evidence`에 저장한다.

- source + canonical payload SHA-256으로 중복 방지
- 같은 원문 재수집 시 새 evidence를 만들지 않음
- parser version 기록
- source record id 보존
- 이후 parser/matcher 변경 시 원문에서 재처리 가능

## CI / Live 검증 분리

일반 `CI`는 외부 API를 호출하지 않는다.

- Ruff
- pytest
- fixture 기반 parser/ingestion/idempotency 검사

실제 API는 `.github/workflows/g2b-live-smoke.yml`의 수동 `workflow_dispatch`에서만 호출한다. 개발계정 호출량과 외부 API 일시 장애가 일반 PR 품질게이트에 영향을 주지 않도록 분리한다.

## 아직 확정하지 않은 것

다음은 실제 근거 없이 추정하지 않는다.

- `getShoppingMallPrdctInfoList`의 필수 검색 파라미터 조합
- `getMASCntrctPrdctInfoList`의 실제 camelCase 응답 alias
- `getDlvrReqDtlInfoList`의 실제 camelCase 응답 alias
- 모델명/제조사명을 서버측에서 직접 검색할 수 있는 최적 파라미터
- `inqryDiv=1`, `inqryPrdctDiv=2` 코드값의 업무적 명칭/의미(동작은 live 검증됨)

## 다음 F1 작업

1. benchmark 품목 3종에 대해 특정품목조달내역 source-hit 여부 확인
2. 페이지네이션 구현 및 최대 페이지 안전장치
3. page-by-page raw evidence 적재 연결
4. 모델 토큰을 `prdctIdntNoNm`에서 후보로 찾는 단계는 F3 matcher와 분리 유지
5. 추가 operation live fixture 확보 후 alias 확장

## F1 완료조건

- [x] GitHub Secret을 통한 실제 API 인증/호출 검증
- [x] 특정품목조달내역 live fixture 확보
- [x] 실제 camelCase 핵심 필드 alias 확정
- [x] 특정품목 검색 파라미터 contract 1종 확정
- [x] raw evidence DB 저장 경로
- [x] 동일 fixture 반복수집 dedupe 테스트
- [x] 서비스키 없는 CI fixture 테스트
- [ ] benchmark 3종 live smoke test
- [ ] pagination + 안전한 중단조건
- [ ] 추가 operation fixture/필드 검증
