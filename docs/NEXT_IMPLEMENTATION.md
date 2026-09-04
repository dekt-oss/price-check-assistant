# 다음 구현 순서

Phase 0는 2026-09-04 종료했다. 최종 검증은 `docs/PHASE0_FINAL_REPORT.md`를 기준으로 한다.

최종 판정은 **Adjust → Phase 1 진행**이다.

## Phase 1-A — 공개가격 수집 coverage 확대

1. G2B Shopping verified 세부품명 mapping 확대
2. exact model 검색·pagination·retry·실패근거 저장 강화
3. `totalCount`가 안전 페이지 한도를 넘으면 날짜구간을 자동 이분할하는 adaptive date partitioning 추가
4. incomplete window 재시도 큐 및 재개 가능한 수집상태 저장
5. Manufacturer official price snapshot의 freshness/재검증 정책 추가
6. 공식가격 변경 감지
7. raw evidence와 normalized observation provenance 강화

YTD 복원력 검증에서 31일 구간의 레이저프린터가 2,000건을 넘어 safety limit에 도달했다. 페이지 한도를 무작정 키우기보다 날짜구간 자동분할을 우선한다. 상세는 `docs/PHASE0_YTD_RESILIENCE_CHECK.md`를 본다.

## Phase 1-B — G2B 계약정보 collector

다음 신규 production-like collector는 `나라장터 계약정보서비스`로 한다.

목표:
- 물품 실제 계약 목록/상세 수집
- 계약총액·수량·단가 관계 검증
- 공고/계약번호 provenance 연결
- Shopping/납품요구 근거와 독립 source로 비교

## Phase 1-C — 가격조건 구조화

Phase 0 Condition Completeness가 0%였으므로 우선순위가 높다.

구조화 대상:
- VAT 포함/별도/미상
- 수량·단위
- 배송비
- 설치비
- 옵션/부속품
- 보증
- 유지보수/서비스 계약
- 거래/기준일

조건이 다른 가격은 숫자가 같아도 동일 조건 가격으로 취급하지 않는다.

## Phase 1-D — 검색 결과 UX

통합검색에서 다음을 명시적으로 보여준다.

- 제품 동일성 A/B/C/D/X
- Evidence Type
- 직접비교 가능/참고만 가능/제외
- source와 기준일
- 가격조건 미상 항목
- `비교근거 부족` 상태
- 다중출처 관측범위

자동 vendor 선정이나 구매결정은 하지 않는다.

## 이후 단계

### 의료기기 안전정보
- 식약처 회수·판매중지정보 source adapter
- 가격근거와 별도 safety evidence로 연결

### 견적서 분석
- Excel 우선 구조적 파싱
- PDF text extraction
- OCR은 최후 수단
- AI는 필드 추출/표준화 보조에 제한

### 내부 이식
- Public PoC 승인 후 별도 진행
- 내부 단가 Excel import부터 검토
- ERP 직접연계는 후순위
