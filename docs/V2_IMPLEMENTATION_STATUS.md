# v2 기획 대비 구현현황

기준: `관리부 구매가격 검색·검토 보조시스템 구축 기획 v2`와 2026-09-05 `main` (`37c9c29c0fa8eb1efd530dd18e7d895aa07ab1ed`) 구현을 대조한다.

상태 정의:

- ✅ 구현: 핵심 기능이 코드와 UI에 존재하고 CI 회귀검증이 있다.
- 🟡 부분구현: 기능은 존재하지만 실제 live/업무 UAT 또는 coverage 확대가 남아 있다.
- ⛔ 외부차단: 공식 API 계약/활용권한 등 외부 조건이 확보되기 전에는 추정 구현하지 않는다.
- ⏸ 후속단계: Public PoC의 실제 업무효과 확인 후 진행할 범위다.

| v2 기능축 | 현재 상태 | 구현된 내용 | 남은 내용 |
|---|---|---|---|
| 직접 제품검색 | 🟡 | 품목명·제조사·모델·규격 입력, Manufacturer/G2B 공개가격 검색 | 최신 Production 브라우저 live smoke, 실제 사용자 UAT, 최종 1화면 통합 |
| 견적서 Excel | 🟡 | `.xlsx/.xls` 품목·제조사·모델·규격·수량·단가·총액 구조추출 | 서로 다른 실제 비식별 양식 최소 5건 UAT |
| 견적서 text PDF | 🟡 | ruled table → word geometry → text fallback 보수적 추출, 실제 synthetic PDF E2E | 실제 공급사 PDF 원문대조 UAT |
| 견적서 scan PDF/OCR | 🟡 | `pypdfium2` raster + 로컬 Tesseract `kor+eng`, 12페이지 안전상한, 실제 image-only synthetic PDF E2E CI | Streamlit Cloud 실제 Tesseract 동작, 실제 스캔 견적 OCR 정확도 UAT |
| 견적 상업조건 | ✅ | VAT·배송·설치·옵션·보증·유지보수·기타조건 원문 명시값 추출 | 다양한 실제 문구 정확도 UAT |
| 견적 ↔ 외부조건 대조 | ✅ | 조건별 `match/conflict/unknown` comparator | 실제 표본의 false match/unknown 비율 측정 |
| 비교가능성 candidate gate | ✅ | A/B·direct price·KRW·양수·수량/단위·VAT·배송·설치·옵션·보증·유지보수·날짜 보수적 gate | 실제 업무 FN/FP 측정, 규칙 임의완화 금지 |
| 담당자 `QUOTE_COMPARABLE` 승인 | ✅ | candidate 통과 pair에 한해 session-level 명시 승인, pair SHA-256, 원본 Evidence 불변, 승인 취소 가능 | 실제 업무 UAT에서 승인 흐름 검증 |
| 나라장터 Shopping/납품가격 | 🟡 | verified exact-model mapping 5개, classification exact filter, pagination/adaptive partition, 단가 의미 검증, 공급업체 근거 | 최신 shared-key live smoke, 실제 source coverage 확인 |
| 나라장터 계약정보 | 🟡 | 품명·기간 계약근거, 계약번호·기관·방법·원문, pagination/dedupe | 대표품목 live smoke, Shopping 교차근거율 확대 |
| G2B 계약 provenance | ✅ | public allow-list, secret-like field 제거, canonical JSON, SHA-256 fingerprint, source record/URL, UI fingerprint | 신규 source에도 같은 계약 적용 |
| 제조사 공개가격 | 🟡 | 검증된 공식 공개가격 snapshot collector | 가격변경 감지, 재검증 정책, 실제 coverage 확대 |
| 일반 공개/B2B/유통가격 | 🟡 | 웹 후보 탐색은 있으나 자동 직접가격 채택은 제한 | UAT에서 coverage 병목 확인 후 source별 검증 adapter |
| A/B/C/D/X 제품매칭 | ✅ | exact 모델·제조사 alias·규격증거·충돌 fail-closed, substring C 차단, C/D 분리 | 실제 ground truth 표본 확대 |
| 핵심 규격 충돌 | ✅ | 용량·전압·전력·저장용량·패키지 수량의 명백한 숫자+단위 충돌 X | 품목군별 안전한 의미규격 규칙 추가 |
| 직접 관측가격 범위 | ✅ | A/B + 직접가격 Evidence Type + KRW + 정상 양수만 관측범위 산정 | 실제 source coverage 확대 |
| 현재 견적 위치 | ✅ | 실제 `QUOTE_COMPARABLE` pair만 상단/하단/범위내 판정 | 실제 승인 pair UAT 및 최종 UI 통합 |
| 가격조건 구조화 | ✅ | 외부근거 + 견적서의 VAT·수량/단위·배송·설치·옵션·보증·유지보수·기준일 구조화 | 실제 UAT로 추출/대조 품질 측정 |
| 가격근거 최신성 | ✅ | 거래일 우선, 없으면 수집/검증일 기준 경과일/재검토 표시 | source별 운영 재검증 주기 정책 |
| 비교 신뢰도 | 🟡 | 독립 source 수 + A/B 직접근거 기반 높음/보통/낮음 | freshness 반영정책, 실제 UAT calibration |
| 출처별 수집상태 | ✅ | 성공 N건 / 정상 0건 / 실패 분리, collector isolation | 운영 이력/재시도 상태 저장은 후속 |
| 원문 근거 추적 | ✅ | URL·근거ID·거래일·수집일·SHA 기반 evidence, G2B 계약 provenance | 신규 source 일관화 |
| 식약처 동일품목/모델 | 🟡 | 품목명 공식조회 후 exact 모델 local match, ambiguous/inactive/export fail-closed | 최신 shared-key live 검증, 모델명 단독 공식 역검색 source 확보 |
| 식약처 업체 업허가 | 🟡 | `Entrps` 공식 조회, active/inactive 상태 | 최신 live 검증, 공식 총판/파트너 근거는 별도 source 필요 |
| 식약처 UDI | 🟡 | 알고 있는 UDI-DI `UDIDI_CD` exact 조회 | known-value live smoke, 모델명→UDI 공식 역조회 계약 확보 |
| 의료기기 경쟁장비 | ✅ | 동일 공식 품목의 국내 정상 등록모델 우선, broad 후보는 조건부 추가조사 후보 | 실제 후보 품질 UAT |
| 공급사 조사 | ✅ | G2B 실제 납품업체 → MFDS 업허가 업체 → 웹 후보 우선순위 | 제조사 공식 총판/파트너 근거 adapter |
| Safety 공식 확인 | 🟡 | exact 모델/허가번호 확인키, 회수·판매중지·행정처분·안전성서한 공식 수동 경로 | 회수·판매중지 자동 API adapter |
| Safety RED 자동경고 | ⛔ | 상태계약과 fail-closed 문구 구현 | 공식 operation/request parameter 확보 후 exact hit 자동경고 |
| API key resolution | ✅ | source-specific → `DATA_GO_KR_MARKET_SERVICE_KEY` → legacy fallback, live workflow 계약테스트 | 실제 최신 key live smoke |
| Secret 비노출 | ✅ | serviceKey URL/error/log redaction, provenance secret-like field 제거, secret 값 artifact 금지 | 신규 외부 client에 동일 규칙 유지 |
| Controlled UAT deterministic gate | ✅ | 15개 프로토콜, 12개 offline 자동 PASS, 3개 live-required, blocker gate/artifact | UAT-04/14/15 실제 live 수행 |
| 실제 견적 UAT | 🟡 | 다중파일 업로드, 원문 대조 editor, 비식별 결과 다운로드, FP/FN·precision/recall·시간·전략별 집계 | 실제 견적 최소 5건 이상 담당자 대조 |
| PostgreSQL 기반 | 🟡 | SQLAlchemy 모델·DB·repository/evidence foundation | Public UI 전체 관측값 지속축적 정책 확정 |
| Public Streamlit PoC | 🟡 | 공개 웹 배포, 기능별 화면, AppTest/startup CI | 최신 main Production 브라우저 + live API + OCR smoke |
| 최종 1화면 UX | ⏸ | 공통 `PurchaseReviewInput` foundation과 통합 설계 | 실제 UAT 결과 반영 후 통합 |
| 내부 구매이력/단가 | ⏸ | 공개 PoC에서는 의도적으로 미사용 | 내부 승인 후 Excel import → PostgreSQL 축적 검토 |
| 진료재료/간납단가 | ⏸ | v2에서 2차 확장으로 명시 | 내부 단가 활용 승인 이후 별도 추진 |

## 현재 단계 판단

핵심 기능의 주요 연결은 구현됐다. 현재 병목은 기능 개수가 아니라 **운영환경과 실제 업무 표본에서의 검증**이다.

```text
견적/제품 입력
→ 제품 identity
→ 공개 직접가격 Evidence
→ 견적조건 ↔ 외부조건 대조
→ candidate gate
→ 담당자 원문/조건 확인
→ 현재 session pair 명시적 승인
→ QUOTE_COMPARABLE
→ assess_prices
→ 현재 견적 위치
```

자동 candidate → `QUOTE_COMPARABLE` 승격은 하지 않는다. 승인된 pair의 원본 public Evidence 자체도 변경하지 않는다.

## 최신 CI 기준

`main` SHA `37c9c29c0fa8eb1efd530dd18e7d895aa07ab1ed` push CI:

- Ruff PASS
- Streamlit 전체 page startup smoke PASS
- 실제 Tesseract system package + `kor`/`eng` language pack 설치 PASS
- 실제 image-only synthetic PDF OCR E2E 포함 pytest PASS
- Match benchmark 100%
- Phase0 offline PASS
- Controlled UAT automated 12/12 PASS
- identity FP 0
- comparison FP 0
- known comparison FN 1: UAT-11 strict quantity mismatch
- release blocker 0

이 결과는 **코드/fixture/Ubuntu Tesseract 경로의 회귀검증**이다. 다음을 증명하지 않는다.

- 최신 Production Streamlit 브라우저 성공
- 현재 shared key의 실제 G2B/MFDS API 성공
- 실제 병원/업체 견적 OCR 정확도
- 실제 구매검토 업무시간 절감

## 현재 우선순위

1. **Live smoke** — G2B Shopping/Phase0, MFDS 품목/업체, UDI-DI, Production Streamlit, Production OCR.
2. **실제 견적 최소 5건 UAT** — 서로 다른 Excel/text PDF/scan PDF 양식을 담당자가 원문 대조.
3. **전체 구매검토 UAT** — identity, Evidence, 조건, candidate, 명시승인, 현재 견적위치를 end-to-end 검증.
4. **UAT 발견 결함 보정** — FP를 최우선, 이후 반복 FN 검토.
5. **Source coverage 확대** — UAT에서 실제 가격근거 확보율이 병목일 때만 확대.
6. **최종 single-screen UI** — 실제 UAT 결과를 반영한 뒤 통합.
7. **내부 이식 검토** — Public PoC 업무효과 확인 및 승인 후 본원 구매단가 Excel import부터 검토.

## UAT에서 반드시 측정할 것

- 품목 추출 성공/실패
- parser 추출전략과 처리시간
- 담당자 원문대조 시간
- 품목 FP/FN, precision/recall
- 제조사/모델/규격/수량/단위/단가/총액/VAT 정확도
- OCR/text PDF/Excel 전략별 차이
- 외부 직접가격 Evidence 확보율
- A/B/C/D/X 사람판정 일치
- 잘못된 직접비교 FP
- 비교 가능한데 보류되는 FN
- 조건 `match/conflict/unknown` 정확도
- candidate gate 통과/보류 사유
- API 실패 vs 정상 0건 구분
- 원문 URL/근거ID/fingerprint 재검증 가능 여부
- 수작업 대비 총 검토시간
- 실제 업무 재사용 가치

특히 **수량 equality 완화 여부는 실제 업무 UAT에서 반복적인 false negative가 확인된 뒤에만 검토**한다.

## 완료로 보지 않는 항목

- CI 성공만으로 실제 데이터/API가 동작했다고 간주하지 않는다.
- synthetic OCR E2E 성공만으로 실제 공급사 스캔 견적 OCR이 완성됐다고 간주하지 않는다.
- 실제 다양한 견적 UAT 전에는 문서추출을 실사용 완성으로 간주하지 않는다.
- candidate gate 통과를 `QUOTE_COMPARABLE` 승인으로 간주하지 않는다.
- Safety 자동 API 미연결/0건을 `안전`으로 간주하지 않는다.
- 계약총액을 제품 단가로 간주하지 않는다.
- 가격조건 명시율이 높다는 이유만으로 직접 비교를 허용하지 않는다.
- source coverage를 늘리기 위해 비공식 가격·검색 snippet·환산 추정가격을 직접가격으로 승격하지 않는다.
