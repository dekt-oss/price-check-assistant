# F1 — 나라장터쇼핑몰 품목정보 Collector

## 목적

`조달청_나라장터쇼핑몰 품목정보 서비스`를 첫 실제 공공조달 가격 Source로 연결한다.

## 2026-09-03 현재 공식 확인 완료

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

F1에서는 우선 가격검토에 직접 필요한 4개 operation만 코드 계약으로 고정한다.

1. 쇼핑몰 품목 등록 내역
2. MAS 계약품목
3. 납품요구 상세
4. 특정품목 조달내역

## 가격 필드 의미 — 공식 파일데이터로 확인한 것

나라장터쇼핑몰 품목 등록 내역에는 `계약단가`가 공개된다.

나라장터쇼핑몰 납품요구 물품 내역에는 `계약단가`, `납품단가`, `납품수량`, `납품금액`, `물품식별`, `물품식별명`, `납품요구번호` 등이 공개된다.

특정품목 조달 내역에는 `단가`, `수량`, `금액`, `물품식별번호`, 계약/납품요구 구분 등이 공개된다.

## 아직 추정 금지

다음은 서비스키로 실제 API를 호출한 fixture가 없으므로 아직 코드에 추정값을 넣지 않는다.

- operation별 검색 파라미터명
- API 응답의 실제 영문/camelCase 필드명
- 품명/물품식별번호 기반 최적 검색 조합
- 페이지네이션의 operation별 필수값

따라서 현재 parser는 공식 파일데이터에서 문서화된 논리 필드명만 처리한다. 실제 API fixture를 확보하면 해당 fixture를 CI에 추가하고 영문 필드 alias를 확정한다.

## Live probe

활용신청 승인 후 로컬 `.env`에만 키를 저장한다.

```text
DATA_GO_KR_SERVICE_KEY=...
```

그 다음 Swagger에서 확인한 operation 파라미터를 그대로 넘긴다.

```powershell
.\.venv\Scripts\python.exe -m purchase_price.scripts.g2b_shopping_probe `
  getShoppingMallPrdctInfoList `
  --param pageNo=1 `
  --param numOfRows=10 `
  --save .local\g2b-shopping-product.json
```

`--param`의 실제 검색 파라미터는 Swagger 명세를 확인한 뒤 추가한다. 위 명령은 구조 예시이며 `pageNo/numOfRows` 외 검색조건을 추정하지 않는다.

## F1 완료조건

- live fixture 최소 3개 확보
- 실제 API 필드 alias 확정
- 실제 검색 파라미터 contract 확정
- raw evidence DB 저장 연결
- 3개 benchmark smoke test
- 동일 fixture 반복수집 dedupe 테스트
- 서비스키 없는 CI에서 fixture 테스트 통과
