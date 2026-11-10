#!/bin/bash
# Stop hook — 이번 턴에 파일/코드/PR/DB 를 바꾸는 도구가 쓰였으면(wcr-post-tool-mark.sh 가 남긴 표시가
# 있으면) 답을 끝내기 전에 work-completion-report 스킬 형식을 지켰는지 확인하라는 리마인더를 강제로
# 주입한다. stop_hook_active 로 같은 턴에서 두 번 막지 않는다(무한루프 방지).
set -uo pipefail

input="$(cat)"
session_id="$(printf '%s' "$input" | jq -r '.session_id // empty' 2>/dev/null)"
stop_hook_active="$(printf '%s' "$input" | jq -r '.stop_hook_active // false' 2>/dev/null)"

[ -n "$session_id" ] || exit 0
marker="${TMPDIR:-/tmp}/claude-wcr-pending-${session_id}"

# 이 Stop 자체가 우리가 방금 건 리마인더 때문에 다시 도는 것이면, 이번엔 그냥 끝낸다.
if [ "$stop_hook_active" = "true" ]; then
  rm -f "$marker" 2>/dev/null || true
  exit 0
fi

# 이번 턴에 상태를 바꾸는 도구가 안 쓰였으면(표시 없음) 조용히 끝낸다.
[ -f "$marker" ] || exit 0
rm -f "$marker" 2>/dev/null || true

cat <<'EOF'
{"decision":"block","reason":"이번 턴에서 파일·코드·PR·DB 등을 바꾸는 도구를 사용했습니다. 답을 마치기 전에 work-completion-report 스킬(또는 이 저장소에 있는 동등한 완료 보고 규칙, 예: verify-before-done)을 실제로 적용했는지 확인하세요. 아직 적용하지 않았다면 지금 Skill 도구로 work-completion-report 를 호출해 그 형식(시키신 것/문제가 뭐였나/어떻게 해결했나/이렇게 확인하세요/다음 작업)으로 다시 보고하세요. 이미 그 형식으로 보고했다면 추가 설명 없이 그대로 끝내면 됩니다. 이번 턴이 파일 읽기·질문 답변처럼 아무것도 바꾸지 않은 턴이었다면 이 리마인더는 무시하세요."}
EOF
exit 0
