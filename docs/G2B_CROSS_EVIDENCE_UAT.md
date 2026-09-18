# G2B Shopping × Contract 교차근거 UAT

## 목적

Issue #4의 남은 완료기준 중 하나인 **Shopping 직접가격 근거와 독립 계약정보 근거의
교차근거율**을 bounded live UAT로 측정한다.

이 UAT는 가격판정 기능이 아니다. 같은 품목 검색어에서 두 독립 공개 source가 각각
근거를 반환하는지와 source 내부 중복 제거 상태를 측정한다.

## 실행

GitHub Actions:

`G2B Cross Evidence Live UAT`

수동 `workflow_dispatch`만 허용한다.

기본 입력:

- 품목: `레이저프린터,인공호흡기,전신가스마취기`
- lookback: 365일
- 품목별 Shopping 1페이지 + Contract 1페이지
- page size: 100
- timeout: 15초
- retry: 1

R2 또는 Streamlit Production Secret은 사용하지 않는다.

## 지표

품목별:

- Shopping API status: `success / success_0 / failure`
- Shopping raw record 수
- explicit `prdctUprc` 직접가격 record 수
- stable source record id 기준 unique 직접가격 수
- source 내부 duplicates removed
- Contract API status
- Contract raw/unique record 수
- cross-evidence hit 여부
- independent source count

전체:

- case count
- 두 source 모두 정상 호출된 case 수
- source failure case 수
- Shopping direct hit case 수
- Contract hit case 수
- cross-evidence case 수
- cross-evidence rate

`cross_evidence_rate`의 분모는 **두 source 호출이 모두 정상인 case만** 사용한다.
API 실패를 정상 0건으로 계산하지 않는다.

## Dedupe 계약

현재 두 API 사이에는 모든 record를 안전하게 동일 거래로 연결할 verified common key가
없다. 따라서 다음 원칙을 사용한다.

1. 각 source 내부에서 stable `source_record_id`가 같은 record만 dedupe한다.
2. Shopping record와 Contract record를 제목/금액/날짜 유사성만으로 같은 거래라고 합치지 않는다.
3. 두 source가 모두 hit한 경우에도 독립 공개근거 2개가 존재한다는 **coverage signal**로만 기록한다.
4. 향후 verified contract/delivery linking key가 확정되면 cross-source dedupe를 별도 구현한다.

## 가격 안전계약

- Contract total은 제품 unit price가 아니다.
- Contract record는 direct price count에 포함하지 않는다.
- 교차근거 hit만으로 `QUOTE_COMPARABLE` 승격하지 않는다.
- A/B identity, VAT, 수량/단위, 설치, 옵션, 보증 등 비교조건 승인 workflow는 기존 규칙을 유지한다.
- cross-evidence rate가 낮더라도 matcher를 자동 완화하지 않는다.

## 완료 판정

이 UAT workflow가 실제 GitHub Secret 환경에서 실행되어:

1. 대표 품목별 Shopping/Contract의 성공·0건·실패가 구분되고,
2. cross-evidence rate가 artifact에 기록되며,
3. 동일 source record replay가 unique count를 부풀리지 않고,
4. Contract total이 직접가격으로 들어가지 않는 것이 확인되면,

Issue #4의 **교차근거율/동일근거 dedupe 실측** 항목을 완료로 전환할 수 있다.
