#!/usr/bin/env bash
# 공통 완료 확인 실행기 (claude-config 에서 자동 배달 — 손으로 고치지 말 것).
# 프로젝트의 scripts/smoke.sh 가 이 파일을 불러 단계를 등록하고 마지막에 finish 를 부른다:
#   source "$(git rev-parse --show-toplevel)/.claude/shared/smoke-run.sh"
#   step "타입 검사" npm run typecheck
#   step "테스트"   npx jest
#   finish
# 마지막 줄은 항상 `SMOKE OK n/n` 또는 `SMOKE FAIL k/n (실패: …)` 이다. 공통 하네스 §1 의 "완료 증거"가 이 줄이다.
# 규칙: 돈이 드는 호출(유료 LLM·이미지·영상)·외부 쓰기·배포는 단계에 넣지 않는다. 몇 분 안에 끝나는 것만.
# 단계는 외부 명령으로 쓴다. 셸 함수를 단계로 쓰면 함수 안의 실패를 직접 `return 1` 해야 실패로 잡힌다.
# finish 를 부르지 않고 끝나면(중간에 빠져나가도) 끝날 때 SMOKE FAIL 을 찍고 실패로 끝낸다 — 이 안전장치는 EXIT trap 이므로
# smoke.sh 에서 `trap ... EXIT` 를 다시 걸지 말 것(덮어써진다). 임시 파일은 finish 직전에 지운다.
set -o pipefail
__smoke_total=0
__smoke_failed=()
__smoke_start=$(date +%s)
__smoke_finished=0
__smoke_on_exit() {
  local code=$?
  if [ "$__smoke_finished" = 0 ]; then
    echo "SMOKE FAIL $((__smoke_total - ${#__smoke_failed[@]}))/$__smoke_total (finish 전에 끝남 — 종료코드 $code)"
    exit 1
  fi
}
trap __smoke_on_exit EXIT

step() {
  local name="$1"; shift
  __smoke_total=$((__smoke_total + 1))
  local t0; t0=$(date +%s)
  echo "── [$__smoke_total] $name: $*"
  if "$@"; then
    echo "   ✓ $name ($(( $(date +%s) - t0 ))초)"
  else
    echo "   ✗ $name ($(( $(date +%s) - t0 ))초)"
    __smoke_failed+=("$name")
  fi
}

finish() {
  __smoke_finished=1
  local ok=$((__smoke_total - ${#__smoke_failed[@]}))
  echo "총 $(( $(date +%s) - __smoke_start ))초"
  if [ "${#__smoke_failed[@]}" -eq 0 ] && [ "$__smoke_total" -gt 0 ]; then
    echo "SMOKE OK $ok/$__smoke_total"
    exit 0
  fi
  local list="단계 없음"
  [ "${#__smoke_failed[@]}" -gt 0 ] && list="$(printf '%s, ' "${__smoke_failed[@]}")" && list="${list%, }"
  echo "SMOKE FAIL $ok/$__smoke_total (실패: $list)"
  exit 1
}
