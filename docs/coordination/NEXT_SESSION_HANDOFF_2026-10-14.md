# 다음 세션 인계 프롬프트 — UX v1.1 마감 뒤 (2026-10-14)

아래 `---` 아래를 새 Claude Code 세션 첫 메시지로 붙여 넣는다.

---

병원 구매정보 도우미(price-check-assistant, Streamlit, 운영 https://bp-price-research.streamlit.app)의 다음 작업을 함께 정하려고 합니다. 코드를 바로 고치지 말고, 먼저 아래를 읽고 후보를 정리한 뒤 저와 논의하세요.

## 지금 상태(2026-10-14, main `5d94c65`)
- UX v1.1(작업지시서 `docs/coordination/UX_V11_WORK_ORDER_v1.2.md`)은 끝났습니다. 가격 트랙 P0~P4, 뉴스·경영 트랙 H0~H2와 후속, 통합 I0까지 머지·배포·운영 실사용 테스트 완료. 요약과 인수 조건 대조는 `docs/coordination/UX_V11_FINAL_REVIEW.md`(6장까지), Codex 최종 리뷰와 응답은 `docs/coordination/history/UX_V11_FINAL_REVIEW_codex*.md`.
- v1.1 작업 브랜치·워크트리(`claude/ux-v11-*`, `codex/ux-v11-*`)는 정리했습니다. 새 작업은 `.worktrees/<이름>`에 새 워크트리를 만들어 하고, main 체크아웃에서는 커밋하지 않습니다.

## 먼저 읽을 것
1. `docs/coordination/UX_V11_FINAL_REVIEW.md` — 4장 "알려진 한계", 6장 실사용 테스트.
2. `docs/performance/UX_V11_PRICE_BASELINE.md` 11장 — 모델별 p50/p95와 단계별 병목.
3. `docs/handoffs/HANDOFF_I0.md`, `HANDOFF_P2b.md`, `HANDOFF_H1.md` 14절.
4. `docs/metrics/price.md`, `news.md`, `hospital_management.md` — 지표 계약(바꾸려면 문서부터).
5. `CLAUDE.md`(보고 형식)와 메모리의 운영 규칙.

## 남은 과제 후보(우선순위 제안)
1. **가격 검색 속도(P2b 2차)**: 브라우저 기준 p50 PNB 10.4 / DFM100 10.1 / HeartOn 16.1 / NT960 18.3초, 목표 10초. 병목은 HeartOn 같은 품목 모델 집계 4.6초, NT960 거래 0건일 때 동일 모델 조회 10.3초, 모든 모델의 앱 진입·통신·다시 그리기 7~8초. 측정 워크플로 `track-b-search-timings.yml`(하루 3회, R2 `state/v1/perf/price-search-timings.json`)로 1주일 표본이 쌓이는 중. 차가운 기동 108초와 피크 메모리 측정 수단도 없음.
2. **뉴스 군집 후속(H1 후속 3)**: 같은 매체의 기획 연재를 한 이슈로 못 묶음(최신순 표본 누락 14/55쌍, 잘못 묶임 0). 허용 누락률 목표를 정하고 연재 규칙 검토. 평가는 `python -m purchase_price.scripts.evaluate_news_issue_clusters --sample newest|importance`(R2 읽기 설정 필요).
3. **작은 UX 어색함 3개**: 견적이 거래 최고가보다 높아도 중앙값 ±20% 안이면 "거래 범위 안"(막대는 "최고보다 높음") — 두 기준을 카드에 한 줄로 설명 / 결과 카드의 낮은 견적 문장에 "단위·구성 확인" 안내 추가(견적 검토 화면에는 있음) / 견적 입력칸 접근성 이름 "내 견적가 (원)"을 라벨 "내 견적 단가"와 맞춤.
4. **운영 배포 안정성**: Streamlit Cloud가 머지 뒤 10~25분 옛 배포를 유지하거나 페이지 파일 일부만 옛 것으로 남긴 일이 3번. 스모크(마커 v25)와 Reboot로 대응 중. 원인·설정 점검 또는 배포 확인 자동화.
5. **저장소 정리**: v1.1 이전의 오래된 워크트리 약 25개(`.worktrees/*`, `.claude/worktrees/agent-*`)와 미머지 원격 브랜치 약 200개. 머지된 것·버릴 것·살릴 것 분류가 필요.
6. **범위 밖으로 남긴 것**: 제품군 수량가중 평균, 관심 모델 감시, 모바일 전용 카드, 품목 여럿일 때 거래 기간 URL 하나, 실제 휴대폰 회전 검증, 외부 조회 실패 운영 화면.

## 일하는 규칙(요약)
- PR은 main으로, CI 초록일 때만 머지. 운영 확인이 필요한 PR은 대시보드 배포 마커(`purchase-workspace-runtime-v26`…)와 스모크 마커를 함께 올린다(`tests/test_ux_v11_integration.py`가 일치 강제).
- 머지 직후 스모크는 재시작과 겹쳐 실패할 수 있다 — 몇 분 뒤 재실행. 문서만 바꾼 머지도 앱을 재시작시키니 문서는 코드 PR에 묶는다.
- 스쿼시 머지 뒤에는 작업 브랜치에 `origin/main`을 다시 합친다(안 하면 다음 PR이 충돌로 CI가 안 돈다).
- 인덱스·저장 형식을 바꿀 때는 읽는 쪽(앱) 먼저 배포하고 운영 확인 뒤 쓰는 쪽(Job)을 바꾼다.
- 판단 문구 금지어: 적정, 권장, 싸다·비싸다, 절감액, 대체 가능, 안전한 제품, 원인 확정, 개선 필요·우수·부진, 인기·대표·추천.
- 보고는 CLAUDE.md의 다섯 덩어리 형식.

## 오늘 논의하고 싶은 것
위 후보 중 무엇을 다음 단계로 할지, 범위와 순서를 제안해 주세요. 각 후보마다 "왜 지금인가 / 1~2주 안에 끝낼 수 있는 범위 / 측정 가능한 완료 기준"을 한 줄씩 붙여 주세요.
