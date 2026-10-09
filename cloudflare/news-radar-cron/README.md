# News Radar 10분 타이머 (Cloudflare Worker)

GitHub Actions의 정기 실행(schedule)은 "가능할 때" 도는 방식이라, 30분마다로 걸어 둔 수집이
2026-10-08 오후부터 다음 날 아침까지 13시간 동안 2번만 실행됐습니다. 우리병원 기사를 10분 안에 잡으려면
정확한 타이머가 필요해서, Cloudflare의 무료 정기 실행(Cron Triggers)이 10분마다 GitHub에 "수집 작업을 시작하라"고
요청하도록 했습니다. 이 Worker는 작업을 시작시키기만 하고, 기사·R2 키·구독자 정보는 전혀 다루지 않습니다.
GitHub 쪽 정기 실행은 예비로 그대로 둡니다(같은 작업이 겹치면 순서대로 돕니다).

## 설정 (처음 한 번, 약 10분)

### 1. GitHub 토큰 만들기 (이 저장소의 작업 시작 권한만)

GitHub → Settings → Developer settings → Personal access tokens → **Fine-grained tokens** → Generate new token
- Repository access: **Only select repositories** → `dekt-oss/price-check-assistant`
- Permissions → Repository permissions → **Actions: Read and write** (다른 권한은 모두 No access)
- 만료일: 1년 권장(만료 전에 새로 만들어 3번만 다시 하면 됩니다)

### 2. Worker 배포

방법 A — 명령어(Node.js 필요):

```bash
cd cloudflare/news-radar-cron
npx wrangler login
npx wrangler deploy
npx wrangler secret put GITHUB_TOKEN
```

마지막 명령에서 1번 토큰을 붙여 넣습니다.

방법 B — 대시보드: Cloudflare → Workers & Pages → Create → Worker 이름 `news-radar-cron` → `worker.js` 내용을 붙여
넣고 Deploy → Settings → Variables에 `GITHUB_REPO=dekt-oss/price-check-assistant`, `WORKFLOW_FILE=news-radar-collect.yml`,
`GIT_REF=main`, Secret `GITHUB_TOKEN`(1번 토큰) → Settings → Triggers → Cron Triggers에 `*/10 * * * *`와 `30 23 * * *` 추가.

### 3. 확인

- `https://news-radar-cron.<계정>.workers.dev/health` 를 열면 `"token_configured": true`가 보이면 성공.
- 10~20분 뒤 GitHub → Actions → News Radar Collect 목록에 `workflow_dispatch` 실행이 10분 간격으로 쌓이면 성공.
