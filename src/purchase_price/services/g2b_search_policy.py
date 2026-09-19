from __future__ import annotations

G2B_DEFAULT_LOOKBACK_DAYS = 1095
G2B_LOOKBACK_OPTIONS = (365, 730, 1095, 1825)


def g2b_lookback_label(days: int) -> str:
    if days == G2B_DEFAULT_LOOKBACK_DAYS:
        return "최근 3년 (기본)"
    if days % 365 == 0:
        return f"최근 {days // 365}년"
    return f"최근 {days}일"
