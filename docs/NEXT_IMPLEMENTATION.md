# 다음 구현 순서

## M0 — 초기세팅 (현재 골격)
- Python/Streamlit/PostgreSQL
- 제품·가격관측 DB 모델
- 외부 수집기 adapter 계약
- A/B 직접비교 가격범위 계산
- 개발용 샘플 검색 화면
- 임시파일 기반 견적 업로드 골격
- 기본 테스트

## M1 — Phase 0 실제 데이터 가능성 조사
1. 대표품목 10~20개 확정
2. 나라장터/공공계약 공개데이터 접근방법 조사
3. 제조사/유통/일반판매 가격 source 후보 선정
4. 품목별 동일모델 식별률, 가격확보율, 조건확인율 측정
5. 결과에 따라 1차 수집원 2~3개를 고정

## M2 — 첫 실제 수집기
- 한 출처를 end-to-end로 구현
- raw evidence와 normalized observation을 분리 저장하도록 DB 확장
- 재수집/중복제거/실패 로그 추가

## M3 — 제품 매칭 v1
- 제조사/모델명 exact normalization
- 규격 token 비교
- A/B/C/D/X 판정 이유 저장
- 자동판정 불확실 시 X 또는 사용자 확인 큐

## M4 — 가격분석 v1
- VAT/수량/단위 정규화
- 설치비·배송비·옵션·보증 조건 표시
- source quality + recentness + match grade 기반 신뢰도 규칙 고도화

## M5 — 의료기기 안전정보
- 식약처 공개정보 source adapter
- 제품 identity와 분리해 매칭 근거 표시

## M6 — 견적서 분석
- Excel 우선(구조적 파싱)
- PDF text extraction
- OCR은 최후 수단
- AI는 필드 추출/표준화 보조에 제한
