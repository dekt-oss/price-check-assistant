# price-check-assistant 구현 로드맵

## 현재 단계

Phase 0 foundation. 목표는 실제 가격 수집기를 붙이기 전에 데이터 계약과 감사 추적 구조를 고정하는 것이다.

## F0 — 기반 구조

- [x] Public 저장소 / CI / PostgreSQL / Streamlit 기본 골격
- [x] A/B/C/D/X 제품 동일성 등급과 EvidenceType 분리
- [x] 20개 Phase 0 benchmark
- [x] API 키를 코드에서 분리하는 환경변수 계약
- [x] collection run / raw evidence / normalized observation 데이터 모델
- [x] raw evidence SHA-256 중복 식별 규칙
- [x] data.go.kr 공통 HTTP client 골격
- [x] Phase 0 benchmark probe 스크립트
- [x] Alembic migration 도입
- [x] DB repository 계층에서 run/evidence idempotent 저장 구현

## F1 — 첫 실제 Collector: 나라장터쇼핑몰 품목정보

목표: 동일 품목의 쇼핑몰 계약단가 및 납품 관련 가격근거를 원문과 함께 수집한다.

- [ ] 공공데이터포털 활용신청 및 개발 서비스키 준비
- [ ] 실제 endpoint / operation / 검색 파라미터 계약을 공식 명세로 고정
- [ ] benchmark 3개로 live smoke test
- [ ] 응답 원문 fixture 저장(비밀키 제거)
- [ ] raw evidence 저장
- [ ] 계약단가/납품단가 EvidenceType 변환
- [ ] pagination / timeout / retry / API 오류 처리
- [ ] 동일 응답 재수집 시 중복 저장 방지

## F2 — 두 번째 Collector: 나라장터 계약정보

- [ ] 물품 계약 목록/상세 operation 확정
- [ ] 품명·기관·계약일·계약번호 등 식별 필드 매핑
- [ ] 전체 계약금액과 단가를 혼동하지 않도록 단위/수량 검증
- [ ] F1과 동일 근거 dedupe 전략 확인

## F3 — Product matching

- [ ] 제조사 정규화
- [ ] 모델명 exact normalization
- [ ] 규격/옵션 token 비교
- [ ] A/B 자동 후보 + X fail-closed
- [ ] C/D는 별도 참고결과로 분리
- [ ] benchmark ground truth 대비 precision/recall 측정

## F4 — Phase 0 runner/report

- [ ] 20개 benchmark 일괄 실행
- [ ] source hit rate
- [ ] direct evidence rate
- [ ] multi-source rate
- [ ] condition completeness
- [ ] traceability rate
- [ ] 품목별 근거부족 사유 출력

## F5 — UI 연결

- [ ] 실제 collector 선택/상태 표시
- [ ] 원문 근거 링크
- [ ] 참고가격 범위 + confidence
- [ ] 예산/기초금액은 직접가격에서 분리 표기
- [ ] API 장애 시 부분결과 + 오류출처 표시

## 구현 규칙

1. 공개가격을 찾지 못하면 `비교근거 부족`으로 끝낸다.
2. 원문 evidence 없이 normalized price만 저장하지 않는다.
3. API 원문에는 서비스키를 절대 저장하지 않는다.
4. 입찰 기초금액/배정예산은 직접가격 범위에 넣지 않는다.
5. collector별 실패는 전체 검색을 중단시키지 않는다.
6. live API 테스트만 두지 않고 비밀정보를 제거한 fixture 테스트를 유지한다.

## 다음 순서

`G2B Shopping collector → 3개 benchmark smoke test → fixture 고정 → 20개 확장`
