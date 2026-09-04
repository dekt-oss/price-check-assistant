# v2 기획 대비 구현현황

기준: `관리부 구매가격 검색·검토 보조시스템 구축 기획 v2`와 2026-09-04 `main` 구현을 대조한다.

상태 정의:
- ✅ 구현: 핵심 기능이 코드와 UI에 존재하고 CI 회귀검증이 있다.
- 🟡 부분구현: 핵심 일부는 동작하지만 기획 범위 전체 또는 실사용 검증이 남아 있다.
- ⛔ 외부차단: 공식 API 계약/활용권한 등 외부 조건이 확보되기 전에는 추정 구현하지 않는다.
- ⏸ 후속단계: Public PoC 검증 후 진행하기로 한 범위다.

| v2 기능축 | 현재 상태 | 구현된 내용 | 남은 내용 |
|---|---|---|---|
| 직접 제품검색 | ✅ | 품목명·제조사·모델·규격 입력, 공개가격 검색 | 최종 1화면 통합 |
| 견적서 Excel | ✅ | `.xlsx/.xls` 품목·제조사·모델·규격·수량·단가·총액 구조추출 | 실제 병원/거래처 다양한 양식 E2E |
| 견적서 PDF | 🟡 | 텍스트 PDF 표 추출, 스캔 PDF fail-closed | 스캔 PDF OCR은 최후수단으로 별도 검토 |
| 견적 상업조건 | 🟡 | `feat/quote-commercial-conditions`에서 VAT·배송·설치·옵션·보증·유지보수·기타조건 명시값 추출 구현 중 | 외부 가격조건과 항목별 비교 |
| 나라장터 쇼핑/납품가격 | ✅ | verified exact-model mapping, pagination/adaptive partition, 단가 의미 검증, 공급업체 근거 | mapping coverage 확대, live 품목군 확대 |
| 나라장터 계약정보 | ✅ | 품명·기간 계약근거, 계약번호·기관·방법·원문, pagination/dedupe | raw provenance 저장 강화, Shopping과 교차근거율 측정 |
| 제조사 공개가격 | 🟡 | 검증된 공식 공개가격 snapshot collector | freshness/재검증 정책, 가격변경 감지, coverage 확대 |
| 일반 공개/B2B/유통가격 | 🟡 | 웹 후보 탐색은 있으나 자동 가격 collector는 제한적 | 신뢰 가능한 사이트별 adapter 또는 검증형 수집정책 |
| A/B/C/D/X 제품매칭 | ✅ | exact 모델·제조사 alias·규격증거·충돌 fail-closed, C/D 분리 | 실제 ground truth 표본 확대 |
| 핵심 규격 충돌 | ✅ | 용량·전압·전력·저장용량·패키지 수량의 명백한 숫자+단위 충돌 X | 품목군별 안전한 의미규격 규칙 추가 |
| 직접 참고가격 범위 | ✅ | A/B + 직접가격 Evidence Type + KRW만 관측범위 산정 | source coverage 확대 |
| 현재 견적 위치 | 🟡 | `quote_comparable` 근거가 있을 때만 상단/하단/범위내 판정 | 견적조건↔외부조건 자동 비교 계약 구축 |
| 가격조건 구조화 | 🟡 | 외부근거 VAT·수량/단위·배송·설치·옵션·보증·유지보수·기준일 표시 | quote-side 조건과 일치/불일치/미확인 비교 |
| 비교 신뢰도 | 🟡 | 독립 source 수 + A/B 직접근거 기반 높음/보통/낮음 | 최신성(freshness)을 신뢰도에 명시적으로 반영 |
| 출처별 수집상태 | ✅ | 성공 N건 / 성공 0건 / 실패 분리, collector isolation | 운영 이력/재시도 상태 저장 |
| 원문 근거 추적 | 🟡 | URL·근거ID·거래일·수집일·SHA 기반 evidence 기초 | 모든 신규 source의 normalized/raw provenance 일관화 |
| 식약처 동일품목/모델 | ✅ | 품목명 공식조회 후 exact 모델 확인, ambiguous/inactive/export fail-closed | 모델명 단독 공식 역검색 source 확보 |
| 식약처 UDI | 🟡 | 알고 있는 UDI-DI `UDIDI_CD` exact 조회 | 모델명→UDI/상세제품 역조회 공식 request 계약 확보 |
| 의료기기 경쟁장비 | ✅ | 동일 공식 품목의 국내 정상 등록모델 우선, broad 후보는 조건부 `추가 조사 후보` | 실제 후보 품질 표본 확대 |
| 공급사 조사 | ✅ | G2B 실제 납품업체 → MFDS 업허가 업체 → 웹 후보 우선순위 | 제조사 공식 총판/파트너 근거 adapter |
| Safety 공식 확인 | 🟡 | exact 모델/허가번호 확인키, 회수·판매중지·행정처분·안전성서한 공식 경로 | 회수·판매중지 자동 API adapter |
| Safety RED 자동경고 | ⛔ | 상태계약과 fail-closed 문구는 구현 | 공식 operation/request parameter 확보 후 exact hit 자동경고 |
| PostgreSQL 기반 | 🟡 | SQLAlchemy 모델·DB·repository/evidence 기반 존재 | Public UI의 모든 관측값을 지속 축적하는 운영정책 확정 |
| Public Streamlit PoC | ✅ | 공개 웹용 Streamlit 기능구성 및 CI | production 실제 브라우저 smoke를 별도 환경에서 지속 검증 |
| 최종 1화면 UX | ⏸ | 공통 `PurchaseReviewInput` foundation | 기능 완성 후 직접검색/견적서/가격/MFDS/Safety를 1화면으로 통합 |
| 내부 구매이력/단가 | ⏸ | 공개 PoC에서는 의도적으로 미사용 | 내부 승인 후 Excel import → PostgreSQL 축적 검토 |
| 진료재료/간납단가 | ⏸ | v2에서 2차 확장으로 명시 | 내부 단가 활용 승인 이후 별도 추진 |

## 현재 단계 판단

핵심 엔진은 **Phase 1~2의 대부분이 구현된 상태**다. 다만 사용자가 실제 견적가격을 검토할 때 가장 중요한 마지막 연결고리인

`견적서 조건 → 외부 가격조건 → quote_comparable 여부 → 현재 견적 위치`

가 아직 완전히 연결되지 않았다.

따라서 화면 통합보다 아래 작업을 먼저 완료한다.

## 다음 우선순위

1. **견적 상업조건 자동추출 완료** — VAT/배송/설치/옵션/보증/유지보수/기타조건
2. **견적조건 ↔ 외부 가격조건 comparator** — 일치/불일치/미확인, 자동 `quote_comparable` 승격은 매우 보수적으로
3. **가격근거 freshness** — 거래일/검증일 기준 최신성 표시, 오래된 snapshot 경고
4. **provenance 일관화** — G2B 계약정보 포함 raw allow-list + fingerprint + normalized record 연결
5. **실제 표본 E2E** — 비식별 실제/대표 견적서와 대표제품으로 end-to-end 검증
6. **Safety 자동 API** — 공식 request contract 확보 즉시 구현
7. **모델→UDI/상세 identity** — 공식 모델 검색 contract 확보 즉시 구현
8. **일반 공개/B2B 가격 source 확대**
9. **최종 single-screen 통합 및 legacy page 정리**
10. **내부 이식 검토** — 승인 후 본원 구매단가 Excel import부터 시작

## 완료로 보지 않는 항목

- CI 성공만으로 실제 데이터/API가 동작했다고 간주하지 않는다.
- 실제 병원/거래처 견적서 다양성 검증 전에는 문서추출 완성으로 간주하지 않는다.
- Safety 자동 API 미연결 상태를 `안전`으로 간주하지 않는다.
- 계약총액을 제품 단가로 간주하지 않는다.
- 가격조건 명시율이 높다는 이유만으로 `quote_comparable`로 자동 승격하지 않는다.
