# 리뷰 점검표 — price-check-assistant (harness-reviewer 가 항목마다 판정)

## 공개 저장소 · 비밀값
- [ ] 실제 본원 구매단가·계약단가·실제 견적서 원본·내부문서·개인정보 파일을 커밋하지 않았다(합성·비식별·공개자료만) — docs/PUBLIC_REPOSITORY_POLICY.md, README "공개 저장소 운영 경계"
- [ ] API key·serviceKey 가 코드·로그·artifact·오류 메시지에 남지 않는다(URL/error/log redaction 유지) — README "나라장터 Shopping", "Shared data.go.kr key 계약"
- [ ] data.go.kr 키 우선순위를 바꾸지 않았다 — 실제 순서는 `src/purchase_price/config.py` 의 `resolved_*_service_key`(README 설명은 일부 낡음)
- [ ] 실제 견적 UAT 다운로드 JSON 에 파일명·원문·제품명·제조사·모델·규격·단가·총액을 넣지 않는다 — README "실제 견적 UAT"

## 외부 호출 · 비용
- [ ] 일반 CI(ci.yml)는 비밀값·외부 API 를 쓰지 않는다. 새 live workflow 는 기본 workflow_dispatch 로 두고, 자동 트리거(schedule·pull_request·push)를 더하면 호출량·비용과 이유를 PR 에 적는다 — ci.yml 머리말, `.github/workflows/` (README "Live validation" 의 '수동 실행만'은 현재 상태와 다름)
- [ ] 견적 원문을 외부 Vision API 로 보내지 않는다(OCR 은 로컬 Tesseract) — README "견적서 구조추출"
- [ ] NAVER 검색결과를 AI 요약·학습에 넘기지 않는다(제목·시간·링크 표시만) — README "AI Hospital Intelligence"
- [ ] R2 쓰기 무료구간 가드(9 GB hard stop, 9.0 초과 설정 불가)를 우회·완화하지 않았다 — docs/R2_ZERO_COST_GUARD_V1.md

## 가격판정 안전규칙 (fail-closed)
- [ ] G2B 자동검색은 data/g2b_product_mappings.csv 의 verified exact-model 만, 매핑이 불명확하면 검색어·분류를 지어내지 않고 건너뛴다 — README "나라장터 Shopping"
- [ ] API 오류와 정상 0건을 구분하고, 1일 구간도 page cap 초과면 부분결과를 성공으로 내지 않는다 — README "나라장터 Shopping", "Live validation"
- [ ] observed_only 근거로 견적 고저를 판정하지 않고, candidate gate 통과만으로 QUOTE_COMPARABLE 로 올리지 않는다(승인은 pair SHA-256 에 묶임) — README "견적 상업조건 / 비교가능성"
- [ ] 예산·기초금액·계약총액을 제품 단가로 쓰지 않고, 비KRW·비정상 금액·C/D/X 등급을 직접 가격범위에 넣지 않는다 — README "가격판정에서 하지 않는 것"
- [ ] 반복 거래건수를 독립 출처 여러 개로 세지 않고, 최저가를 적정가·구매권고로 자동판단하지 않는다 — README "가격판정에서 하지 않는 것"
- [ ] 수량 동일성(quantity equality) 조건을 완화하지 않았다(UAT-11 FN 1건은 알려진 것) — README "테스트 / CI"
- [ ] MFDS: ambiguous permit 은 fail-closed, 취소·취하/수출전용은 자동승격 금지, 업허가를 공식 총판으로 확장 해석하지 않는다 — README "의료기기 조사"
- [ ] 회수·판매중지 adapter 와 모델명→UDI 역검색을 공식 계약 확인 없이 추정 구현하지 않았다 — README "의료기기 조사"

## 구조 · 운영
- [ ] DB 스키마를 바꾸면 alembic/versions 에 새 리비전을 더했다(기존 리비전 수정 금지는 문서 근거 없는 일반 관행) — alembic/versions/, tests/test_*_migration.py
- [ ] ci.yml 의 PRODUCTION_PYTHON 을 바꾸면 docs/operations/CURRENT_OPERATIONS.md 도 같이 맞췄다 — ci.yml test-production-python 주석
- [ ] 의존성은 pyproject.toml 과 requirements.txt(운영 cloud 설치 경로) 양쪽에서 깨지지 않는다 — docs/operations/CURRENT_OPERATIONS.md "패키지 설치"
- [ ] `bash scripts/smoke.sh` 마지막 줄이 `SMOKE OK` 다(ci.yml `test` 작업과 같은 단계 — 운영 Python 작업 `test-production-python` 은 포함 안 됨) — scripts/smoke.sh
- [ ] 보고에서 CI green 을 실제 G2B/MFDS API·Production 성공으로 쓰지 않고, 성공 N건 / 정상 0건 / 실패 / 미검증을 구분한다 — README "Live validation"
