#!/bin/bash
# PostToolUse hook — 파일/코드/PR/DB 를 바꾸는 도구가 쓰이면 "이번 턴에 뭔가 바뀌었다" 표시만 남긴다.
# Stop 훅(wcr-stop-reminder.sh)이 이 표시를 보고 완료 보고 리마인더를 넣을지 판단한다.
# 멱등·비대화식. 실패해도 절대 도구 호출을 막지 않는다(항상 exit 0).
set -uo pipefail

input="$(cat)"
session_id="$(printf '%s' "$input" | jq -r '.session_id // empty' 2>/dev/null)"
[ -n "$session_id" ] || exit 0

marker="${TMPDIR:-/tmp}/claude-wcr-pending-${session_id}"
touch "$marker" 2>/dev/null || true
exit 0
