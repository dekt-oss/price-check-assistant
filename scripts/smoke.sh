#!/usr/bin/env bash
# 완료 확인용 스모크: CI(.github/workflows/ci.yml) 의 오프라인 관문을 그대로 돌린다. 외부 API·유료 호출 없음.
cd "$(git rev-parse --show-toplevel)" || { echo "SMOKE FAIL 0/0 (git 저장소 밖)"; exit 1; }
source .claude/shared/smoke-run.sh

# 가상환경이 있으면 그 파이썬을 쓰고, 없으면 PATH 의 python 을 쓴다(scripts/test.sh 와 같은 기준).
if [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY=python; fi

# 1. 린트 — pyproject [tool.ruff] 설정
step "ruff 검사" "$PY" -m ruff check .
# 2. Streamlit 전체 화면 기동 스모크
step "Streamlit 화면 기동" "$PY" -m pytest -q tests/test_streamlit_startup_smoke.py
# 3. 전체 테스트(실제 PDF/OCR 합성 E2E 포함 — tesseract kor/eng 가 필요)
step "pytest 전체" "$PY" -m pytest -q
# 4. 매칭 벤치마크 — 정답과 등급이 하나라도 어긋나면 실패
step "매칭 벤치마크" "$PY" -m purchase_price.scripts.evaluate_match_benchmark \
  --fail-on-mismatch \
  --output artifacts/match-benchmark-predictions.csv \
  --summary-output artifacts/match-benchmark-summary.json
# 5. Phase 0 오프라인 통합 점검
step "Phase0 오프라인 점검" "$PY" -m purchase_price.scripts.run_phase0_validation \
  --offline --begin-date 20260714 --end-date 20260813 \
  --output-dir artifacts/phase0-validation-offline
# 6. Controlled UAT 결정적 오프라인 관문
step "Controlled UAT 오프라인" "$PY" -m purchase_price.scripts.run_controlled_uat \
  --fail-on-blocker --output-dir artifacts/controlled-uat-offline

finish
