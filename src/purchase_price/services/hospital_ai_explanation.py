"""AI 경영분석 설명 (Benchmark Phase 4).

The plan's rule is "수치 = deterministic calculation, 해석 = AI". This module is the only place
that talks to Claude, and it enforces that rule in code:

* The model sees **only** numbers already computed by ``hospital_metrics`` (comparison rows,
  deterministic findings, data-quality notes). No raw statements, no news, no NAVER data.
* The answer is checked before it is shown: every number in it must appear in the input. An
  answer that introduces a new figure is discarded and the caller falls back to the
  deterministic sentences.
* Without an API key, or on any API failure or refusal, ``explain`` returns ``None`` and the
  screen keeps the deterministic findings. Nothing on the page depends on the model.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from purchase_price.services.hospital_metrics import ComparisonRow, Finding, format_metric

MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_OUTPUT_TOKENS = 4000

SYSTEM_PROMPT = """\
당신은 병원 관리부 직원에게 공개 회계자료 비교 결과를 설명하는 도우미입니다.

입력으로 받는 것은 프로그램이 이미 계산한 지표, 비교군 평균, 위치, 계산 문장, 자료 상태 메모뿐입니다.
이 숫자들은 모두 정확하다고 보고 그대로 인용하세요.

지켜야 할 것:
- 입력에 없는 숫자를 만들지 마세요. 새로 더하거나 빼거나 비율을 다시 계산하지 마세요. 연도도 입력에 있는 것만 씁니다.
- 원인을 단정하지 마세요. 원인은 "확인이 필요하다"는 형태로, 어떤 세부 항목(예: 약품비와 진료재료비)을 나눠 보면 좋은지만 제안합니다.
- 자료 상태 메모(회계기간 차이, 자본잠식, 병상수 없음 등)가 결론에 영향을 주면 반드시 한 문장으로 짚어 주세요.
- 전문용어는 쉬운 말로 풀고, 4~6문장의 평이한 한국어 문단 하나로 답하세요. 제목, 목록, 표는 쓰지 마세요.
"""


@dataclass(frozen=True)
class ExplanationInput:
    target_name: str
    fiscal_year: int
    peer_label: str
    peer_names: tuple[str, ...]
    rows: tuple[dict[str, Any], ...]
    findings: tuple[str, ...]
    quality_notes: tuple[str, ...]

    def to_json(self) -> str:
        payload = {
            "기준 병원": self.target_name,
            "회계연도": self.fiscal_year,
            "비교 방식": self.peer_label,
            "비교 병원": list(self.peer_names),
            "지표": list(self.rows),
            "계산 문장": list(self.findings),
            "자료 상태": list(self.quality_notes),
        }
        # Sorted keys and fixed separators keep the prompt byte-stable for caching.
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_input(
    *,
    target_name: str,
    fiscal_year: int,
    peer_label: str,
    peer_names: Iterable[str],
    rows: Sequence[ComparisonRow],
    findings: Sequence[Finding],
    quality_notes: Iterable[str] = (),
) -> ExplanationInput:
    """Collect only computed, display-formatted figures for the model."""

    row_payload = tuple(
        {
            "지표": row.label,
            "값": format_metric(row.value, row.unit),
            "비교군 평균": format_metric(row.peer_average, row.unit),
            "비교 병원 수": row.peer_count,
            "위치": row.position_text,
        }
        for row in rows
    )
    return ExplanationInput(
        target_name=target_name,
        fiscal_year=fiscal_year,
        peer_label=peer_label,
        peer_names=tuple(peer_names),
        rows=row_payload,
        findings=tuple(finding.text for finding in findings),
        quality_notes=tuple(note for note in quality_notes if note),
    )


_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> set[str]:
    found: set[str] = set()
    for match in _NUMBER_RE.findall(text):
        normalized = match.replace(",", "")
        found.add(normalized)
        if "." in normalized:
            found.add(normalized.rstrip("0").rstrip("."))
    return found


def unsupported_numbers(answer: str, source: ExplanationInput) -> set[str]:
    """Numbers in ``answer`` that do not appear in the input (the guard against invented figures).

    Small counting words such as "3년" or "2곳" are allowed only if those digits occur in the
    input as well, so the rule stays one simple check.
    """

    allowed = _numbers(source.to_json())
    return {number for number in _numbers(answer) if number not in allowed}


@dataclass(frozen=True)
class Explanation:
    text: str
    model: str
    input_tokens: int
    output_tokens: int


def resolve_api_key(secrets: Mapping[str, Any] | None = None) -> str | None:
    value = os.getenv("ANTHROPIC_API_KEY")
    if value and value.strip():
        return value.strip()
    if secrets is not None:
        try:
            candidate = secrets.get("ANTHROPIC_API_KEY")
        except Exception:  # noqa: BLE001 - Streamlit raises when no secrets file exists
            candidate = None
        if candidate and str(candidate).strip():
            return str(candidate).strip()
    return None


class ExplanationError(RuntimeError):
    """The model could not produce a usable explanation; the caller shows deterministic text."""


def explain(source: ExplanationInput, *, api_key: str | None, client: Any | None = None) -> Explanation:
    """Ask Claude for a short plain-language paragraph about the computed comparison.

    Raises ``ExplanationError`` when no key is configured, the API fails, the model declines,
    or the answer contains a number that is not in the input.
    """

    if client is None:
        if not api_key:
            raise ExplanationError("AI 설명 연결 설정이 없습니다.")
        import anthropic  # imported lazily so the page works without the package installed

        client = anthropic.Anthropic(api_key=api_key, max_retries=2, timeout=120.0)

    try:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=MAX_OUTPUT_TOKENS,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            output_config={"effort": "low"},
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            messages=[
                {
                    "role": "user",
                    "content": "아래 계산 결과를 설명해 주세요.\n\n" + source.to_json(),
                }
            ],
        )
    except Exception as exc:  # noqa: BLE001 - any SDK/network error falls back to computed text
        raise ExplanationError(f"AI 설명 요청 실패: {type(exc).__name__}") from exc

    if getattr(response, "stop_reason", None) == "refusal":
        raise ExplanationError("AI가 이 요청에 답하지 않았습니다.")
    text = "".join(
        getattr(block, "text", "") for block in response.content if getattr(block, "type", "") == "text"
    ).strip()
    if not text:
        raise ExplanationError("AI 설명이 비어 있습니다.")
    invented = unsupported_numbers(text, source)
    if invented:
        raise ExplanationError(
            "AI 설명에 계산 결과에 없는 숫자가 있어 표시하지 않았습니다: " + ", ".join(sorted(invented))
        )
    usage = getattr(response, "usage", None)
    return Explanation(
        text=text,
        model=str(getattr(response, "model", MODEL)),
        input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
    )


def deterministic_paragraph(findings: Sequence[Finding]) -> str:
    """Fallback text: the computed sentences joined into one paragraph."""

    if not findings:
        return "비교군 평균과 눈에 띄게 다른 지표가 없거나, 비교할 자료가 부족합니다."
    return " ".join(finding.text for finding in findings)
