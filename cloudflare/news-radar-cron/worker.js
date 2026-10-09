// Cloudflare Worker: start the News Radar collector on GitHub every 10 minutes.
//
// GitHub Actions `schedule` events are best-effort and were observed running ~2 times in 13 hours
// for a 30-minute schedule (2026-10-08/09). Cloudflare Cron Triggers fire reliably, so this Worker
// calls GitHub's workflow_dispatch API on a timer. It only starts a workflow; it never sees news,
// R2 keys or subscriber data.
//
// Secrets (wrangler secret put ...):
//   GITHUB_TOKEN  fine-grained token, repository = dekt-oss/price-check-assistant only,
//                 permission "Actions: Read and write". Nothing else.
// Vars (wrangler.toml): GITHUB_REPO, WORKFLOW_FILE, GIT_REF

const API = "https://api.github.com";

async function dispatch(env, mode) {
  const url = `${API}/repos/${env.GITHUB_REPO}/actions/workflows/${env.WORKFLOW_FILE}/dispatches`;
  const response = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "news-radar-cron-worker",
    },
    body: JSON.stringify({ ref: env.GIT_REF || "main", inputs: { mode } }),
  });
  // 204 No Content on success. Never echo the token.
  return { status: response.status, ok: response.status === 204 };
}

export default {
  // "*/10 * * * *" -> collect; "30 23 * * *" (08:30 KST) -> daily digest. See wrangler.toml.
  async scheduled(event, env, ctx) {
    const mode = event.cron === "30 23 * * *" ? "digest" : "collect";
    const result = await dispatch(env, mode);
    if (!result.ok) {
      console.error(`workflow_dispatch ${mode} failed: HTTP ${result.status}`);
    }
  },

  // GET /health shows the configuration is present (never the token itself).
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/health") {
      return Response.json({
        repo: env.GITHUB_REPO,
        workflow: env.WORKFLOW_FILE,
        token_configured: Boolean(env.GITHUB_TOKEN),
      });
    }
    return new Response("news-radar-cron", { status: 200 });
  },
};
