# MFDS 의료기기 시장조사 구현 상태

작성일: 2026-09-04

## 기준선

- base: `main`
- 시작 기준 commit: `82951a5182ffd1a1521ad2389bb1ba266ca042e9`
- branch: `phase2/mfds-device-intelligence`

## 이번 구현 M1

### 완료

- `docs/MFDS_DEVICE_INTELLIGENCE.md`
  - 병원 구매부서 관점의 목표/업무흐름 정의
  - 동일 식약처 품목만 자동 경쟁후보로 허용
  - 사용목적/주요사양 유사도 기반 광범위 추천 금지
  - 제조·수입업체 / 공공조달 공급업체 / 공식 판매채널 근거등급 설계
  - 회수·판매중지 및 안전성서한을 가격과 분리한 safety layer 설계

- `src/purchase_price/services/mfds_device_intelligence.py`
  - MFDS 공통 response/body/items unwrap
  - 의료기기 형명정보 adapter
  - 제조·수입업 허가정보 adapter
  - pagination / date / yes-no / 상태 parser
  - 취소·취하 및 수출전용 모델의 일반 경쟁후보 제외 속성

- `pages/4_의료기기_시장조사.py`
  - 식약처 품목명으로 동일 품목 등록모델 조회
  - 일반 경쟁후보와 취소/수출전용 분리 표시
  - 업체명으로 의료기기 제조/수입/판매/임대 허가정보 조회
  - 서비스키 미설정 시 fail-closed
  - 동일 품목이 임상적 대체성을 의미하지 않는다는 경고 표시

- `tests/test_mfds_device_intelligence.py`
  - API error header fail-closed
  - single/list item envelope
  - model parser
  - 취소/수출전용 후보 제외
  - 공식 `PRDLST_NM` filter 호출
  - pagination
  - 업체 parser
  - 공식 `Entrps` filter 호출

- `.env.example`, `config.py`
  - MFDS endpoint override / timeout / retry 설정 추가
  - 기존 `DATA_GO_KR_SERVICE_KEY`를 공통 공공데이터포털 인증키로 재사용

## 아직 미구현

### M2 exact model identity

- 의료기기 표준코드별 제품정보 API의 live request filter 검증
- 견적서 모델명 → UDI/품목명/분류번호/허가번호/제조·수입업체 자동 연결
- 정확한 response field casing fixture 고정

### M3 공급시장

- 제품별 제조·수입업체 자동 join
- 기존 G2B 실제 납품업체와 join
- 제조사 공식 대리점/파트너 근거 adapter

### M4 safety

- 의료기기 회수·판매중지 API adapter
- exact 모델/허가번호 RED 경고
- 품목 수준 AMBER 경고
- 식약처 안전성서한 링크/검색

### M5 견적서 통합

- XLSX 견적서에서 추출한 행별 `의료기기 조사` 연결
- 가격근거와 MFDS 시장조사 결과의 단일 화면 통합

## 검증 경계

이번 M1은 공공데이터포털 공식 명세에서 request/response가 명확히 확인된 다음 두 API만 production-like adapter로 구현한다.

1. 의료기기 형명정보
   - `MdeqModlInfoService01/getMdeqModlInq01`
   - 품목명 filter: `PRDLST_NM`
2. 의료기기 제조·수입업 허가정보
   - `MdlpMnfcturPrmisnInfoService01/getMdlpMnfcturPrmisnList01`
   - 업체명 filter: `Entrps`

표준코드별 제품정보와 회수·판매중지 source는 존재와 제공정보를 확인했지만, 이 브랜치에서는 live parameter/response contract가 고정되기 전까지 추정 구현하지 않는다.
