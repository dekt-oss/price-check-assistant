# 병원 경영 Benchmark — 공개 자료 출처와 접근 방법 (2026-10-08 조사)

Phase 3(기획서 4.2~4.7, 5장)에서 Benchmark 화면을 실제 공개 자료로 채우기 위해 확인한 출처다.
각 항목에 "확인함"(이 저장소에서 실제로 호출·내려받기를 해 본 것)과 "미검증"(문서만 보고 적은 것)을 나눠 적는다.

## 1. KHIDI 의료기관 회계정보 공시 (재무상태표 · 손익계산서) — 확인함

- 사이트: **의료기관 회계정보 공시사이트** <https://haspa.khidi.or.kr> (한국보건산업진흥원 운영)
- 근거: 「의료기관 회계기준 규칙」 제11조 제2항 — 개설자가 법인인 100병상 이상 병원은 재무상태표와
  손익계산서를 보건복지부장관이 정하는 사이트에 공시. 2016 회계연도분부터 공시.
- 로그인: **필요 없음.** 조회 · 엑셀 · PDF 내려받기 모두 공개.
- 조회 가능 회계연도(2026-10-08 화면 기준): 2016 ~ 2024.

### 화면 경로 (사람이 직접 받을 때)

1. <https://haspa.khidi.or.kr/total-public-inq> (상단 메뉴 "공시정보조회")
2. "회계연도"에서 연도 선택, "기관명"에 병원 이름 일부(예: `백병원`, `부산대학교`) 입력 → 검색
3. 결과 줄의 "재무 상태표" / "손익 계산서" 돋보기 → 팝업 아래 "엑셀다운로드"
   (또는 목록에서 체크 후 "재무상태표 일괄 다운로드" / "손익계산서 일괄 다운로드")
4. 받은 `.xls` 파일을 `python -m purchase_price.scripts.import_hospital_financials --file <경로> --hospital <병원명>`
   으로 적재한다.

### 프로그램 접근 (화면이 내부적으로 부르는 주소, 확인함)

| 용도 | 주소 | 응답 |
| --- | --- | --- |
| 기관 검색 | `GET /total-public-inq?y={연도}&hn={기관명}` | HTML 목록. 각 줄에 `getIS('{연도}', '{기관코드}')` |
| 손익계산서 | `GET /api/total-is/{기관코드}?y={연도}` | JSON `{result:"ok", json:{info, one[], three[]}}` |
| 재무상태표 | `GET /api/total-sfp/{기관코드}?y={연도}` | JSON 같은 구조 |
| 엑셀(단건) | `GET /file/totalpublic/excel?typ=IS|SFP&y={연도}&hc={기관코드}` | BIFF `.xls` |
| PDF(단건) | `GET /file/totalpublic/pdf?typ=IS|SFP&y={연도}&hc={기관코드}` | PDF |

- JSON `one[]` 줄: `accCode`(8자리 표준 계정코드), `accName2`(들여쓰기 포함 계정명),
  손익계산서는 `profitAmt`(당기) · `profitAmt1`(전기), 재무상태표는 `basAmt` · `basAmt1`. 단위는 원.
- `info.map`: 손익계산서는 `cFyyyy/cFmonth/cFday ~ cTyyyy/cTmonth/cTday`(당기 회계기간),
  재무상태표는 `cyyyy/cmonth/cday`(당기말 기준일).
- `info`에는 병상수(`bsNum`), 종별(`kindName`), 설립형태(`foundName`)도 있다. 화면 하단 문구상 이 일반현황은
  "해당 연도 말 건강보험심사평가원 자료"를 가져다 쓴 값이다.
- 기관코드는 8자리(예: 인제대학교부산백병원 `21100063`)이며 연도마다 같은지 적재기가 매년 검색해 확인한다.
- 우리는 **당기 금액만** 쓴다. 다음 해 공시의 "전기" 금액은 재작성될 수 있어 섞지 않는다.

### 회계연도 규칙 (확인함)

- 공시 "회계연도 2024"는 **그 해에 시작한 회계기간**이다. 예: 인제대학교부산백병원(학교법인) 2024 =
  2024-03-01 ~ 2025-02-28. 국립대병원 · 의료법인은 대체로 1월~12월이다.
- 그래서 같은 "2024"라도 병원마다 기간이 다를 수 있고, 화면은 기간이 다른 병원을 따로 경고한다
  (`hospital_metrics.fiscal_period_warnings`).

### 8개 병원 기관코드 (2024 공시 검색 결과)

| 병원 Master | HASPA 기관명 | 기관코드 | 공시 종별 · 병상수(2024) |
| --- | --- | --- | --- |
| H-BUSAN-PAIK | 인제대학교부산백병원 | 21100063 | 상급종합병원 · 810 |
| H-HAEUNDAE-PAIK | 인제대학교 해운대백병원 | 21100608 | 종합병원 · 866 |
| H-ILSAN-PAIK | 인제대학교일산백병원 | 31100651 | 종합병원 · 551 |
| H-SANGGYE-PAIK | 인제대학교 상계백병원 | 11100818 | 종합병원 · 468 |
| H-PNUH | 부산대학교병원 | 21100021 | 상급종합병원 · 1048 |
| H-PNUYH | 양산부산대학교병원 | 38100509 | 상급종합병원 · 1142 |
| H-DAUH | 동아대학교병원 | 21100390 | 상급종합병원 · 973 |
| H-KOSIN | 고신대학교복음병원 | 21100039 | 상급종합병원 · 844 |

연도별 실제 적재 결과는 `data/hospital_financial.csv`와 아래 "적재 현황"을 본다.

### 계정 대응 (HASPA 계정코드 → `hospital_metrics.ACCOUNT_LABELS`)

| 우리 키 | HASPA 코드 | HASPA 계정명 |
| --- | --- | --- |
| medical_revenue | 60100000 | Ⅰ.의료수익 |
| inpatient_revenue | 60101000 | 1.입원수익 |
| outpatient_revenue | 60102000 | 2.외래수익 |
| medical_expense | 60200000 | Ⅱ.의료비용 |
| labor_cost | 60201000 | 1.인건비 |
| material_cost | 60202000 | 2.재료비 |
| drug_cost | 60202010 | 약품비 |
| supply_cost | 60202020 | 진료재료비 |
| admin_cost | 60203000 | 3.관리운영비 |
| medical_profit | 60300000 | Ⅲ.의료이익(손실) |
| non_medical_revenue | 60400000 | Ⅳ.의료외수익 |
| non_medical_expense | 60500000 | Ⅴ.의료외비용 |
| net_income | 61100000 | 당기순이익(순손실) |
| current_assets | 10100000 | Ⅰ.유동자산 |
| total_assets | 10000000 | 자산총계 |
| current_liabilities | 20100000 | Ⅰ.유동부채 |
| short_term_borrowings | 20100020 | 단기차입금 |
| current_long_term_debt | 20100080 | 유동성장기부채 |
| employee_short_term_borrowings | 20100120 | 임직원단기차입금 |
| long_term_borrowings | 20200010 | 장기차입금 |
| foreign_long_term_borrowings | 20200020 | 외화장기차입금 |
| total_liabilities | 20000000 | 부채총계 |
| total_equity | 30000000 | 자본총계 |

`borrowings`(차입금)는 공시에 한 줄로 없으므로 위 5개 차입 계정의 합으로 **코드가 계산**한다(추정 아님,
합산 규칙은 `hospital_metrics.BORROWING_COMPONENTS`).

## 2. 심평원(HIRA) 병원정보 — data.go.kr, 키 미승인

| 서비스 | data.go.kr | 주소 | 쓰는 오퍼레이션 |
| --- | --- | --- | --- |
| 건강보험심사평가원_병원정보서비스 | <https://www.data.go.kr/data/15001698/openapi.do> | `https://apis.data.go.kr/B551182/hospInfoServicev2` | `getHospBasisList` (병원명 `yadmNm`으로 검색 → `ykiho`(암호화 요양기호), `clCdNm`(종별), `addr`, `sidoCdNm`, `estbDd`, `drTotCnt`) |
| 건강보험심사평가원_의료기관별상세정보서비스 | <https://www.data.go.kr/data/15001699/openapi.do> | `https://apis.data.go.kr/B551182/MadmDtlInfoService2.8` | `getEqpInfo2.8` (`ykiho` 필수 → `permSbdCnt` 허가병상수, `stdSickbdCnt`, `hghrSickbdCnt` 등) |

- 오퍼레이션 이름과 응답 항목은 2026-10-08 data.go.kr Swagger 화면에서 읽었다(확인함). 상세정보서비스는 현재
  버전이 **2.8**이다(2.7 주소는 `code=12 NO_OPENAPI_SERVICE_ERROR`).
- **키 상태(2026-10-08 실호출):** 워크트리 `.env`의 data.go.kr 키 4개(`DATA_GO_KR_SERVICE_KEY` 등) 모두
  `hospInfoServicev2/getHospBasisList`에 `HTTP 403 code=30 SERVICE_KEY_IS_NOT_REGISTERED_ERROR`.
  즉 **병원정보서비스 활용신청이 안 되어 있다.** 상세정보서비스 2.8도 같은 키로는 쓸 수 없다(미신청, 미검증).
- 해결: data.go.kr 로그인 → 위 두 서비스 페이지에서 "활용신청" (자동승인, 반영까지 최대 1시간) →
  `python -m purchase_price.scripts.sync_hira_hospital_info` 실행.
- 그 전까지 `data/hospital_master.json`의 병상수 · 종별 확정은 비워 둔다. 화면은 "자료 없음"과
  "종별 확인 전"을 보여 준다.
- 참고: HASPA 공시 목록의 병상수 · 종별도 심평원 연말 자료를 옮긴 값이지만, 공시 연도 기준의 옛 값이고 출처가
  간접이라 병원 Master 확정값으로 쓰지 않는다. 대신 화면의 "자료 상태" 상자에 "공시 당시 병상수"로만 보여 줄 수 있다.

## 3. ALIO (공공기관 경영정보 공개시스템) — 다음 단계

- 사이트: <https://www.alio.go.kr> — 부산대학교병원은 교육부 소관 기타공공기관으로 경영공시 대상.
- 공시 항목 중 "요약 재무상태표", "요약 손익계산서", "임직원 수", "신규채용" 등이 있다(미검증: 부산대학교병원의
  기관 ID와 항목 번호는 이번에 확인하지 못함).
- 주의(미검증): ALIO 공시는 **법인 단위**라 본원과 양산부산대학교병원이 합쳐져 있을 수 있다. 병원별 비교는
  HASPA(병원 단위)를 쓰고, ALIO는 인력 · 부채 · 정부지원 같은 보조 지표용으로 Phase 4에서 붙인다.

## 적재 현황

`python -m purchase_price.scripts.import_hospital_financials --fetch` 실행 결과로 아래를 채운다.
