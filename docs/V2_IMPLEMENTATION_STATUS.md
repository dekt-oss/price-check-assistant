# v2 기획 대비 구현현황

기준: `관리부 구매가격 검색·검토 보조시스템 구축 기획 v2`와 2026-09-04 `main` (`0f143319d5827ec630d237f7f80eefbac335a06d`) 구현을 대조한다.

상태 정의:
- ✅ 구현: 핵심 기능이 코드와 UI에 존재하고 CI 회귀검증이 있다.
- 🟡 부분구현: 핵심 일부는 동작하지만 기획 범위 전체 또는 실사용 검증이 남아 있다.
- ⛔ 외부차단: 공식 API 계약/활용권한 등 외부 조건이 확보되기 전에는 추정 구현하지 않는다.
- ⏸ 후속단계: Public PoC 검증 후 진행하기로 한 범위다.

| v2 기능축 | 현재 상태 | 구현된 내용 | 남은 내용 |
|---|---|---|---|
| 직접 제품검색 | ✅ | 품목명·제조사·모델·규격 입력, Manufacturer/G2B 공개가격 검색 | 최종 1화면 통합, 실제 사용자 UAT |
| 견적서 Excel | ✅ | `.xlsx/.xls` 품목·제조사·모델·규격·수량·단가·총액 구조추출 | 다양한 비식별 실사용 양식 UAT |
| 견적서 PDF | 🟡 | text PDF 추출, 스캔 PDF fail-closed | 실제 text PDF UAT, OCR은 최후수단으로 별도 검토 |
| 견적 상업조건 | ✅ | PR #50: VAT·배송·설치·옵션·보증·유지보수·기타조건의 원문 명시값 추출 | 다양한 견적 문구에서 정확도 UAT |
| 견적 ↔ 외부조건 대조 | ✅ | PR #50: 조건별 `match/conflict/unknown` comparator | 실제 표본의 false match/unknown 비율 측정 |
| 비교가능성 candidate gate | ✅ | PR #51: A/B·direct price·KRW·양수·수량/단위·VAT·배송·설치·옵션·보증·유지보수·날짜 보수적 gate | 담당자 확인/승인 후 현재 pair만 본 `QUOTE_COMPARABLE`로 연결하는 workflow |
| 나라장터 쇼핑/납품가격 | ✅ | verified exact-model mapping 5개, classification code exact filter, pagination/adaptive partition, 단가 의미 검증, 공급업체 근거 | source coverage와 기간별 live UAT 확대 |
| 나라장터 계약정보 | 🟡 | 품명·기간 계약근거, 계약번호·기관·방법·원문, pagination/dedupe | PR #53 provenance, Shopping 교차근거율, 대표품목 live smoke |
| 제조사 공개가격 | 🟡 | 검증된 공식 공개가격 snapshot collector | 가격변경 감지, 재검증 운영정책, coverage 확대 |
| 일반 공개/B2B/유통가격 | 🟡 | 웹 후보 탐색은 있으나 자동 가격 collector는 제한적 | 신뢰 가능한 사이트별 adapter 또는 검증형 수집정책 |
| A/B/C/D/X 제품매칭 | ✅ | exact 모델·제조사 alias·규격증거·충돌 fail-closed, substring C 차단, C/D 분리 | 실제 ground truth 표본 확대 |
| 핵심 규격 충돌 | ✅ | 용량·전압·전력·저장용량·패키지 수량의 명백한 숫자+단위 충돌 X | 품목군별 안전한 의미규격 규칙 추가 |
| 직접 관측가격 범위 | ✅ | A/B + 직접가격 Evidence Type + KRW + 정상 양수만 관측범위 산정 | source coverage 확대 |
| 현재 견적 위치 | 🟡 | 실제 `ComparisonScope.QUOTE_COMPARABLE` 근거에만 상단/하단/범위내 판정 | candidate → 담당자 승인 → session pair 승격 연결 |
| 가격조건 구조화 | ✅ | 외부근거 + 견적서의 VAT·수량/단위·배송·설치·옵션·보증·유지보수·기준일 구조화 | UAT로 추출/대조 품질 측정 |
| 가격근거 최신성 | ✅ | PR #52: 거래일 우선, 없으면 수집/검증일 기준 경과일/재검토 표시 | source별 운영 재검증 주기와 신뢰도 연계 정책 |
| 비교 신뢰도 | 🟡 | 독립 source 수 + A/B 직접근거 기반 높음/보통/낮음 | freshness를 어떻게 반영할지 정책 확정, UAT calibration |
| 출처별 수집상태 | ✅ | 성공 N건 / 성공 0건 / 실패 분리, collector isolation | 운영 이력/재시도 상태 저장 |
| 원문 근거 추적 | 🟡 | URL·근거ID·거래일·수집일·SHA 기반 evidence | G2B 계약정보 provenance PR #53, 신규 source 일관화 |
| 식약처 동일품목/모델 | ✅ | 품목명 공식조회 후 exact 모델 확인, ambiguous/inactive/export fail-closed | 모델명 단독 공식 역검색 source 확보 |
| 식약처 UDI | 🟡 | 알고 있는 UDI-DI `UDIDI_CD` exact 조회 | 모델명→UDI/상세제품 역조회 공식 request 계약 확보 |
| 의료기기 경쟁장비 | ✅ | 동일 공식 품목의 국내 정상 등록모델 우선, broad 후보는 조건부 `추가 조사 후보` | 실제 후보 품질 UAT |
| 공급사 조사 | ✅ | G2B 실제 납품업체 → MFDS 업허가 업체 → 웹 후보 우선순위 | 제조사 공식 총판/파트너 근거 adapter |
| Safety 공식 확인 | 🟡 | exact 모델/허가번호 확인키, 회수·판매중지·행정처분·안전성서한 공식 수동 경로 | 회수·판매중지 자동 API adapter |
| Safety RED 자동경고 | ⛔ | 상태계약과 fail-closed 문구는 구현 | 공식 operation/request parameter 확보 후 exact hit 자동경고 |
| PostgreSQL 기반 | 🟡 | SQLAlchemy 모델·DB·repository/evidence 기반 존재 | Public UI의 모든 관측값을 지속 축적하는 운영정책 확정 |
| Public Streamlit PoC | ✅ | 공개 웹 배포, 기능별 Streamlit 화면, AppTest/CI | production 브라우저 + live API 반복 smoke |
| 최종 1화면 UX | ⏸ | 공통 `PurchaseReviewInput` foundation과 통합 설계문서 | Controlled UAT 후 직접검색/견적서/identity/Safety/가격/경쟁/공급사 통합 |
| 내부 구매이력/단가 | ⏸ | 공개 PoC에서는 의도적으로 미사용 | 내부 승인 후 Excel import → PostgreSQL 축적 검토 |
| 진료재료/간납단가 | ⏸ | v2에서 2차 확장으로 명시 | 내부 단가 활용 승인 이후 별도 추진 |

## 현재 단계 판단

핵심 엔진은 **Controlled UAT를 시작할 수 있는 수준**이다. 과거 문서에서 미완료로 잡혀 있던 다음 세 기능은 이미 `main`에 반영됐다.

1. 견적 상업조건 추출 및 견적 ↔ 외부조건 comparator — PR #50
2. quote comparability candidate gate — PR #51
3. evidence freshness — PR #52

따라서 현재 병목은 기능의 개수보다 **실사용 검증과 마지막 승인 연결**이다.

```text
견적/제품 입력
→ 제품 identity
→ 공개 직접가격
→ 견적조건 ↔ 외부조건 대조
→ candidate gate
→ 담당자 원문/조건 확인
→ 현재 검토 pair에 대한 명시적 승인
→ QUOTE_COMPARABLE
→ assess_prices
→ 현재 견적 위치
```

자동 candidate → `QUOTE_COMPARABLE` 승격은 하지 않는다.

## 현재 우선순위

1. **Provenance 일관화 마무리** — G2B 계약정보 public allow-list + canonical JSON + SHA-256 + source record/URL + normalized record 연결. PR #53 open, CI success, 승인 전 미merge.
2. **Controlled UAT** — 대표 10개 이상 케이스로 추출·identity·Evidence·조건·candidate gate·원문추적·업무시간을 측정.
3. **담당자 승인형 본 비교 workflow** — 현재 session의 quote/evidence pair에만 명시적 승인상태를 부여하고 `assess_prices`에 연결. 영구 source 자체의 scope를 바꾸지 않음.
4. **Live smoke** — G2B Shopping/계약, MFDS 품목/업체, UDI-DI, production Streamlit을 일반 CI와 분리해 검증.
5. **Source coverage 확대** — 제조사 공식 공개가격 → 검증 가능한 공공계약 → 신뢰 가능한 B2B/유통 순서.
6. **최종 single-screen UI** — UAT 결과를 반영한 뒤 통합.
7. **내부 이식 검토** — Public PoC의 업무효과 확인 및 승인 후 본원 구매단가 Excel import부터 검토.

## UAT에서 반드시 측정할 것

- 품목 추출 성공/실패
- 제조사/모델/규격 정확도
- 외부 직접가격 Evidence 확보율
- A/B/C/D/X 사람판정 일치
- 잘못된 직접비교 false positive
- 비교 가능한데 보류되는 false negative
- 조건 `match/conflict/unknown` 정확도
- candidate gate 통과/보류 사유
- API 실패 vs 정상 0건 구분
- 원문 URL/근거ID/fingerprint로 재검증 가능한지
- 수작업 대비 검토시간
- 실제 업무 재사용 가치

특히 **수량 equality 완화 여부는 UAT에서 false negative가 확인된 뒤에만 검토**한다.

## 완료로 보지 않는 항목

- CI 성공만으로 실제 데이터/API가 동작했다고 간주하지 않는다.
- 실제 다양한 비식별 견적 UAT 전에는 문서추출을 실사용 완성으로 간주하지 않는다.
- candidate gate 통과를 `QUOTE_COMPARABLE` 승인으로 간주하지 않는다.
- Safety 자동 API 미연결/0건을 `안전`으로 간주하지 않는다.
- 계약총액을 제품 단가로 간주하지 않는다.
- 가격조건 명시율이 높다는 이유만으로 직접 비교를 허용하지 않는다.
- source coverage를 늘리기 위해 비공식 가격·검색 snippet·환산 추정가격을 직접가격으로 승격하지 않는다.
