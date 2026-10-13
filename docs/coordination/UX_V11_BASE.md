# UX v1.1 작업 — Gate 0 기록

| 항목 | 값 |
| --- | --- |
| 작업지시서 | `docs/coordination/UX_V11_WORK_ORDER_v1.2.md` |
| 기준 브랜치 | `main` |
| BASE_SHA | `ecb888bada895fec30443a951dfc09ab2e90a54e` (PR #342 머지 커밋, 2026-10-12) |
| 시작 시각 | 2026-10-12 (KST) |
| Track P 브랜치 / 워크트리 | `claude/ux-v11-price` / `.worktrees/ux-v11-price` |
| Track H 브랜치 / 워크트리 | `codex/ux-v11-news-management` / `.worktrees/ux-v11-news-management` (Codex가 자체 워크트리를 쓰면 같은 브랜치를 체크아웃) |
| Integration 브랜치 / 워크트리 | `claude/ux-v11-integration` / `.worktrees/ux-v11-integration` (`8a84477`에서 생성, I0-a) |
| Integration 담당 | Claude (사용자 확정 2026-10-13) |
| PR #341 상태 | 머지됨(`8a84477`, 2026-10-13) |

## 재사용 금지 워크트리
`.worktrees/claude-price`(브랜치 `news-radar-30min`), `.claude/worktrees/agent-*`(과거 작업), `~/.codex/worktrees/windows-test-reliability`(PR #341 작업분). 이번 작업에는 쓰지 않는다.

## 로컬 실행 분리
- Track P: Streamlit 포트 8502~8509
- Track H: Streamlit 포트 8602~8609, `NEWS_RADAR_INDEX_PATH=.local/news-radar.json.gz`
- 두 트랙 모두 `main` 체크아웃(`C:\Users\임준혁\projects\price-check-assistant`)에서는 커밋하지 않는다.
