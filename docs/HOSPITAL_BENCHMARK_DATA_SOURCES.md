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

## 3. ALIO (공공기관 경영정보 공개시스템) — 확인함 (2026-10-09 조사 · 적재)

- 사이트: <https://alio.go.kr> — 부산대학교병원은 교육부 소관 기타공공기관. **기관 ID `C0071`**
  (기관별 공시 화면 `https://alio.go.kr/organ/organDisclosureDtl.do?apbaId=C0071`).
- 접근: **로그인 없이** 공개 화면으로 읽는다. `robots.txt`는 `Allow: /`. 저작권정책(<https://alio.go.kr/notice/copyright.do>)은
  공공데이터법에 따라 영리 목적 포함 자유 이용을 보장한다고 적혀 있다. 요청은 1.5초 간격으로 보낸다.
- 화면 주소(확인함, 서버가 HTML 조각을 돌려줌):
  1. `GET /item/itemReportTerm.do?apbaId=C0071&reportFormRootNo={항목번호}` → 최신 `disclosureNo`
  2. `GET /item/itemReportRight.do?disclosureNo={번호}` → 보고서 표 HTML
- 쓰는 항목번호: 임직원 수 `2020`, 신규채용 현황 `2040`, 요약 재무상태표 `3120`, 요약 손익계산서 `3130`,
  장단기 차입금 `3180`. (확인만 하고 안 쓴 것: 직원 평균보수 `2060`, 수입·지출현황 `31401`.)
- **법인 단위(확인함):** 알리오에는 "양산부산대학교병원"이 따로 없다(병원 기관 목록에 부산대학교병원 `C0071`,
  부산대학교치과병원 `C0853`만 있음). 임직원 수 공시 작성자 부서에 양산인력개발팀 · 양산진료행정팀이 들어 있고,
  2024 매출 8,693억 원은 HASPA 부산대병원 단독 의료수익 4,118억 원보다 훨씬 커서 HASPA 두 병원 합(8,609억 원)에
  가깝다. 즉 숫자는 **본원+양산 합산**이다. 화면 안내 문구는 `alio_disclosure.ALIO_SCOPE_NOTE`.
- 적재 결과: `data/alio_disclosure.csv` 180줄, 연도 2021~2025(연말 결산) + 2026(임직원 수 · 신규채용만, 2분기 기준).
  원본 HTML은 `data/alio_raw/`에 출처 주소 · 가져온 시각과 함께 보관한다. 값이 "-"(해당 없음)인 칸은 저장하지 않는다.
  - 인력(명): 임직원 정원 합계, 정규직 정원 · 현원, 기간제 현원, 용역 인력, 여성 현원
  - 신규채용(명): 정규직 신규채용, 청년 · 여성 · 비수도권 지역인재
  - 재무상태표 · 손익계산서(백만원, 일반 회계 K-GAAP), 부채비율 · 매출액순이익률(%)
  - 차입금: 장기 · 단기 기말잔액, 변동금액(백만원), 차입금 의존도(%)
- 명령: `python -m purchase_price.scripts.import_alio_disclosure --fetch` (내려받기 + CSV 재생성),
  `--from-raw` (저장된 원본만으로 CSV 재생성, 몇 번을 돌려도 같은 결과).
- 화면 연결: `alio_disclosure.alio_table_for(hospital_id)`(항목 × 연도 표), `alio_rows_for(hospital_id)`(긴 형식).
  `H-PNUH`와 `H-PNUYH`는 같은 법인 자료를 돌려주고 다른 병원은 빈 목록이다.
- 한계: 분기 보고서는 항상 "최신 1건"만 받는다(표 안에 과거 5개 연도가 함께 들어 있어 연도 이력은 충분).
  과거에 공시된 값이 나중에 고쳐졌는지는 비교하지 않는다. 주무기관 점검으로 표 서식이 바뀌면 파서가 해당 줄을 못 찾아
  조용히 빠질 수 있다(미검증: 서식 변경 시 동작).

### data.go.kr 경로 (확인함: 쓸 만한 것 없음)

- 재정경제부_공공기관 채용정보 조회서비스 <https://www.data.go.kr/data/15125273/openapi.do>
  (`https://apis.data.go.kr/1051000/recruitment` · `/list` · `/detail`)는 알리오의 **채용공고**만 준다.
  임직원 수 · 손익 · 재무는 없다. 워크트리 키로 호출하면 `HTTP 403 code=30 SERVICE_KEY_IS_NOT_REGISTERED_ERROR`
  (활용신청 안 됨). 개발단계 자동승인. 이번 목적에는 필요 없어 신청하지 않았다.
- 재정경제부_공공기관 정보 조회 서비스 <https://www.data.go.kr/data/15125287/openapi.do>는 기관 이름 · 유형 · 소속 부처 정보다
  (호출해 보지 않음, 미검증). 임직원 · 재무 항목 OpenAPI는 data.go.kr 검색에서 찾지 못했다(미검증: 검색 한계).
- 따라서 **활용신청이 필요한 것은 없다.** 알리오 공개 화면으로 충분하다.

## 적재 현황 (2026-10-08)

`python -m purchase_price.scripts.import_hospital_financials --fetch --years 2016-2024` 결과:
**8개 병원 × 2016~2024 = 72개 병원-연도 모두 적재**(병원-연도당 23계정, 총 1,656줄).
원본 JSON은 `data/khidi_raw/{연도}/{기관코드}_{IS|SFP}.json`(약 4.3MB)에 출처 주소 · 가져온 시각과 함께 보관한다.

| 병원 | 연도 | 회계기간 |
| --- | --- | --- |
| 부산백 · 해운대백 · 일산백 · 상계백 · 동아대 · 고신대복음 (학교법인) | 2016~2024 | 3월 1일 ~ 다음 해 2월 말 |
| 부산대 · 양산부산대 (국립대병원) | 2016~2024 | 1월 1일 ~ 12월 31일 |

확인된 특이사항:

- 부산백병원은 2016~2018 공시에 기관명이 `(학교법인)인제대학교부산백병원`이다. 적재기는 앞의 법인 표시만
  떼고 병원 명단과 맞춘다(`khidi_financials.resolve_disclosed_name`).
- 동아대학교병원 2024 손익계산서의 끝 날짜가 `2025년 02월 29일`(없는 날짜)로 공시되어 있다. 끝 날짜는
  같은 해 재무상태표 기준일(2025-02-28)을 쓴다.
- 2024 공시의 자본총계가 0 이하인 병원(부산백 · 고신대복음 · 상계백)은 부채비율을 계산하지 않는다.
- 공시 종별(2024): 일산백 · 상계백 · 해운대백은 "종합병원"으로 나온다. 병원 Master의 일산백 "상급종합병원"은
  공시와 다르다. 심평원 연계(활용신청 후) 때 확정한다 — 그 전까지 화면은 "종별 확인 전"으로 표시한다.

엑셀 파서(`parse_haspa_xls`)는 부산백 2024 손익계산서 · 재무상태표 실제 내려받은 파일로 검증했다
(`tests/fixtures/khidi/`). 다른 병원 · 연도의 엑셀은 같은 서식이라고 보고 있으나 직접 열어 보지는 않았다(미검증).

## 심평원 병상·종별 동기화 (2026-10-09)

- data.go.kr 활용신청은 **계정 단위**다. `.env`에 다른 계정의 키가 섞여 있으면 승인된 서비스도 code 30을 돌려준다.
  `sync_hira_hospital_info`는 설정된 data.go.kr 키를 차례로 시험해 병원정보서비스가 받아 주는 키를 쓴다
  (`HIRA_SERVICE_KEY`를 따로 두면 그 키가 먼저다). 2026-10-09에는 `G2B_RESEARCH_SERVICE_KEY`가 통했다.
- 38곳 모두 이름 하나로 일치했다. 심평원 이름이 다른 곳은 별칭으로 맞췄다: 강동경희대병원 = "강동경희대학교병원",
  온종합병원 = "의료법인 온병원그룹의료재단 온병원". 심평원 종별 "상급종합"은 "상급종합병원"으로 맞춘다.
- 병상수 쓰임: **유사 규모 묶음은 심평원 현재 허가병상수**(`bed_count`, 예: 부산백 776), **병상당 지표는 그 해 회계공시
  병상수**(`disclosed_bed_count` 계정, 예: 부산백 2024 810)로 나눈다. 같은 해 수익과 병상을 맞추기 위해서다.
