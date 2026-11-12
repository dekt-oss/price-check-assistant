# 작업 순서 — 기획 · Codex 리뷰 · 구현 · 페이블 최종 검사 (공통 하네스 §3 의 기본 방식)

> ⚠️ claude-config `shared/ORCHESTRATE.md` 에서 배달된 사본이다. 여기서 고치지 말 것.
> 소유자 결정 2026-11-10(순서)·2026-11-12(속도 조정·한도 초과 자동 생략). Claude Code 가 주 작업자일 때의 순서다.
> **검사 명령·머지 방식·PR 규칙·보고 형식은 그 저장소 `CLAUDE.md`(와 `scripts/smoke.sh`)가 정본**이고, 이 문서는 순서만 정한다.

## 작업 크기별 경로
| 크기 | 경로 |
|---|---|
| **큰 작업**(사용자가 "기획부터", 또는 여러 화면·스키마·외부 배포에 걸친 일) | ① 기획 → ② Codex 계획 리뷰 → ③ 기획자 재검토·확정 → **소유자 승인(한 번 멈춤)** → ④ 구현 → ⑤ Codex 코드 리뷰 → ⑥ 페이블 최종 검사 → ⑦ 머지·보고 |
| **간단한 작업** | ④ 구현 → ⑥ 페이블 최종 검사 → ⑦ (Codex 안 부름) |
| 문서만 | 검사 생략(보고에 "문서만 — 검사 생략"). 단 CLAUDE.md 가 검사를 필수로 정했으면 그대로 한다 |

간단함의 기준: 범위가 한 문장으로 정해지고 마이그레이션·새 화면·유료 호출·외부 배포가 없는 일. 애매하면 큰 작업으로 본다.
보고에 "큰 작업으로 봤다 / 간단한 작업으로 봤다"를 적는다.

**재검사 규칙(시간 절약):** Codex 는 재검사하지 않는다 — 지적을 고치거나 "반영 안 함 + 이유"를 적고 넘어가고, 반영이 맞는지는 페이블이 본다.
페이블은 **❌ 가 있었을 때만** 재검사한다(⚠️ 는 고치거나 이유를 적는다). 고친 커밋이 생기면 smoke(또는 검사 명령)는 다시 돌린다.
페이블 검사는 **최종 HEAD** 에서 받는다.

## ① 기획 · ③ 확정
- 기획자는 소유자가 연 세션의 모델이다(큰 작업은 페이블, 중간 작업은 오퍼스일 수 있다).
- 계획서 `docs/plans/YYYY-MM-DD-<이름>.md`: 목표 · 범위 밖 · 바뀌는 파일 · 검증 방법 · 되돌리는 법 · 배포 순서(있으면).
- Codex 지적은 하나씩 재검토해 받을 것은 반영, 안 받을 것은 계획서에 이유를 적고 소유자 승인을 받는다.

## ④ 구현
- 판단은 지금 세션이, 정해진 편집은 보조 에이전트(`Agent`, model `sonnet`, 어려운 편집은 `opus`)에 나눠 맡길 수 있다.
  같은 파일을 둘이 동시에 고치지 않게 나눈다. 보조 에이전트에게 `git stash`·브랜치 전환을 금지한다.
- 끝나면 `bash scripts/smoke.sh`(없으면 CLAUDE.md 검사 명령) 마지막 줄을 확인한다. CLAUDE.md 가 커밋 직전 검사를 정했으면 그것도.

## ② · ⑤ Codex 리뷰 (큰 작업만)
Codex 는 **읽기 전용**, ChatGPT 구독 한도를 쓴다(API 종량제 아님).
- 사전 확인: `codex --version` 이 0.167 미만이면 `npm i -g @openai/codex@latest`(옛 판은 gpt-6.1-sol 을 "ChatGPT 계정 미지원"으로 거절).
  명령을 못 찾으면 `$env:PATH = "$env:APPDATA\npm;$env:PATH"`. `codex login status` 가 `Logged in using ChatGPT` 가 아니면 **멈추고 묻는다**.
- 모델은 `-m gpt-6.1-sol`. `~/.codex/config.toml` 은 고치지 않는다.
- `codex review --base` 는 지시문을 못 받으므로 `codex exec -s read-only` 를 쓴다. stdin 은 비운다(`"" |`).
- **범위를 좁힌다**: 바뀐 파일·직접 호출처·점검표만 보게 한다(넓게 훑으면 4~5분, 좁히면 1~2분 — 2026-11-12 실측 278초→72초).
- 코드 리뷰는 **커밋된 것만** 본다 → 먼저 커밋. 기준은 **`origin/main`**: 리뷰 직전 `git fetch origin` 하고
  `git log --oneline origin/main..HEAD` 에 이 작업 커밋만 보이는지 확인(로컬 main 이 뒤처져 남의 커밋 46개를 리뷰한 적 있음).
- `<이름>` = 브랜치 이름의 마지막 `/` 뒤. 결과는 `outputs/reviews/`(git 무시 — 아니면 .gitignore 에 추가).

계획 리뷰:
```powershell
New-Item -ItemType Directory -Force outputs/reviews | Out-Null
$log = "" | codex exec -m gpt-6.1-sol -s read-only -o outputs/reviews/<이름>-plan-codex.md "docs/plans/<파일>.md 계획서만 리뷰하라. 필요하면 계획서가 언급한 파일만 열고 저장소를 넓게 훑지 마라. 빠진 영향 범위·되돌리기 어려운 단계·검증 방법의 빈틈·더 단순한 대안을 한국어로 짧게 지적하라. 파일을 고치지 마라. 마지막 줄은 '판정: 진행' 또는 '판정: 계획 수정 필요'." 2>&1 | Out-String
```

코드 리뷰:
```powershell
git fetch origin; New-Item -ItemType Directory -Force outputs/reviews | Out-Null
$log = "" | codex exec -m gpt-6.1-sol -s read-only -o outputs/reviews/<이름>-code-codex.md "git diff origin/main...HEAD 로 이 브랜치 변경만 리뷰하라. 바뀐 파일과 그 직접 호출처, .claude/review-checklist.md 만 읽고 저장소를 넓게 훑지 마라. 계획서가 있으면 docs/plans/<파일>.md 와 대조하라. 버그·데이터 손실·보안·빠진 호출처·테스트 공백만 file:line 근거와 함께 한국어로 짧게 적어라. 점검표 항목 중 해당 없는 것은 적지 마라. 파일을 고치지 마라. 마지막 줄은 '판정: 통과' 또는 '판정: 수정 필요 (N건)'." 2>&1 | Out-String
```
- 반론은 한 번만: `"" | codex exec resume --last "<반론>"`. 종료 코드와 걸린 시간을 보고에 적는다.

### Codex 를 못 쓸 때 — 자동으로 건너뛴다(묻지 않음)
**성공 판단이 먼저다**: `$LASTEXITCODE -eq 0` 이고 `-o` 결과 파일이 생겼으면 성공 — 그때는 `$log` 를 보지 않는다
(Codex 가 읽은 diff 가 `$log` 에 섞여 "usage limit" 같은 글자가 들어 있을 수 있다, 2026-11-12 오탐).
실패했을 때만 `$log` 의 `ERROR:` 줄로 판단한다. 어느 경우든 **페이블 최종 검사는 반드시 받는다** — 검사 0개로 머지하지 않는다.
| 실패 시 `ERROR:` 줄 | 할 일 |
|---|---|
| `usage limit` | 건너뜀. PR·보고에 "Codex 한도 초과로 생략(풀리는 시각 …)" |
| `not supported when using Codex with a ChatGPT account` | `npm i -g @openai/codex@latest` 후 한 번만 재시도, 안 되면 건너뜀 |
| 로그인·그 밖의 오류 | 건너뜀. 보고 맨 위에 원인 한 줄(예: "Codex 로그인 필요") |

## ⑥ 페이블 최종 검사 (코드를 바꾼 모든 작업)
- 검사 AI 는 공통 하네스 §3 대로 고른다(CLAUDE.md 가 이름으로 지정한 것, 없으면 `harness-reviewer`) — **model 은 `fable`**.
  목록에 그 에이전트가 없으면 `general-purpose` + model `fable` 로 띄우고 첫 줄에 "`.claude/agents/<검사 AI>.md` 를 읽고 그대로 따르라"고 쓴다.
- 넘길 것만: 브랜치 이름, 계획서 경로(있으면), 사용자 요구사항 **원문**, Codex 리뷰 파일 경로(있으면). **내 결론은 넘기지 않는다.**
- 판정 줄을 그대로 보고에 옮긴다.

## ⑦ 머지 · 보고
- 머지 방식은 CLAUDE.md 규칙대로(에이전트 머지 허용 여부는 저장소마다 다르다).
- PR 설명에 검사 요약: Codex 판정 또는 생략 사유, 페이블 판정, 반영 안 한 지적과 이유.
- 외부 배포(서버 함수·production 업데이트)는 도구가 확인을 요구하면 소유자 승인을 받는다.
