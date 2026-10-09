"""Shared look for every page: colours, sizes and small HTML building blocks.

The values come from docs/design/DESIGN_DECISIONS.md: GPT's blue palette and component sizes,
Claude Design's layout. Streamlit's own widgets get their colours from .streamlit/config.toml;
this module only styles the HTML cards the pages draw themselves (class prefix ``pc-``), so a
Streamlit upgrade that renames its internal classes cannot break the layout.
"""

from __future__ import annotations

import html
from collections.abc import Iterable

import streamlit as st

APP_NAME = "병원 구매정보 도우미"
THEME_MARKER = "app-theme-v1"

PRIMARY = "#1D4ED8"
NAVY = "#183153"
TEAL = "#0F766E"
SUCCESS = "#047857"
WARNING = "#B45309"
DANGER = "#B42318"
BACKGROUND = "#F4F7FB"
SURFACE = "#FFFFFF"
SUBTLE = "#EFF4FA"
BORDER = "#DCE4EE"
TEXT = "#172B4D"
MUTED = "#66768D"

# Status dot / pill tones. Colour never carries meaning alone: every pill also has a word.
TONE_OK = "ok"
TONE_INFO = "info"
TONE_WARN = "warn"
TONE_DANGER = "danger"
TONE_MUTED = "muted"
TONES = (TONE_OK, TONE_INFO, TONE_WARN, TONE_DANGER, TONE_MUTED)

THEME_CSS = f"""
<style>
:root {{
  --pc-primary:{PRIMARY}; --pc-navy:{NAVY}; --pc-teal:{TEAL}; --pc-success:{SUCCESS};
  --pc-warning:{WARNING}; --pc-danger:{DANGER}; --pc-bg:{BACKGROUND}; --pc-surface:{SURFACE};
  --pc-subtle:{SUBTLE}; --pc-border:{BORDER}; --pc-text:{TEXT}; --pc-muted:{MUTED};
}}
.block-container {{max-width:1240px; padding-top:2rem; padding-bottom:3rem;}}
h1 {{letter-spacing:-0.9px; color:var(--pc-navy);}}
h2, h3 {{letter-spacing:-0.4px; color:var(--pc-navy);}}
[data-testid="stVerticalBlockBorderWrapper"] {{background:var(--pc-surface);}}
[data-testid="stSidebar"] {{border-right:1px solid var(--pc-border);}}
.pc-brand {{display:flex; align-items:center; gap:10px; font-weight:800; font-size:17px;
  color:var(--pc-navy); margin:0 0 18px 2px; letter-spacing:-0.4px;}}
.pc-brandmark {{width:34px; height:34px; border-radius:10px; flex:none; color:#fff; font-size:19px;
  display:grid; place-items:center; background:linear-gradient(135deg,#2459DF,{TEAL});}}
.pc-navgroup {{color:#8391A3; font-size:12px; font-weight:700; letter-spacing:.4px; margin:16px 0 4px 4px;}}
.pc-sidefoot {{color:#8D98A8; font-size:11px; line-height:1.6; margin-top:24px;}}
.pc-card {{background:var(--pc-surface); border:1px solid var(--pc-border); border-radius:13px;
  box-shadow:0 2px 11px rgba(23,52,89,.035); padding:16px 18px;}}
.pc-eyebrow {{color:var(--pc-teal); font-weight:800; font-size:12px; margin-bottom:8px;}}
.pc-eyebrow.pc-muted {{color:var(--pc-muted);}}
.pc-title {{font-size:29px; font-weight:800; letter-spacing:-0.9px; color:var(--pc-navy); margin:0 0 6px 0;}}
.pc-subtitle {{font-size:13px; color:var(--pc-muted); margin:0 0 10px 0;}}
.pc-section-title {{font-size:17px; font-weight:700; color:var(--pc-navy); margin:0 0 12px 0;}}
.pc-metrics {{display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin:0 0 14px 0;}}
.pc-metric {{position:relative; min-height:99px; padding:16px 18px;}}
.pc-metric .pc-label {{font-size:12px; color:#697C91;}}
.pc-metric .pc-value {{font-size:22px; font-weight:800; margin:8px 0 5px 0; color:var(--pc-navy);
  line-height:1.25; word-break:keep-all;}}
.pc-metric .pc-sub {{font-size:11px; color:#7A899B; line-height:1.5;}}
.pc-dot {{position:absolute; top:16px; right:16px; width:9px; height:9px; border-radius:50%;}}
.pc-dot.pc-ok {{background:{SUCCESS};}} .pc-dot.pc-info {{background:{PRIMARY};}}
.pc-dot.pc-warn {{background:#D97706;}} .pc-dot.pc-danger {{background:{DANGER};}}
.pc-dot.pc-muted {{background:#A3AFBF;}}
.pc-chips {{display:flex; flex-wrap:wrap; gap:7px; margin:8px 0 12px 0;}}
.pc-chip {{display:inline-block; background:var(--pc-subtle); color:#50637B; border-radius:6px;
  padding:5px 9px; font-size:11px; line-height:1.4;}}
.pc-chip b {{color:#25466B;}}
.pc-pill {{display:inline-block; border-radius:15px; padding:4px 9px; font-size:11px; font-weight:800;}}
.pc-pill.pc-ok {{background:#E8F7F1; color:#137B57;}}
.pc-pill.pc-info {{background:#EBF2FF; color:#2456BF;}}
.pc-pill.pc-warn {{background:#FFF3DF; color:#9A5D0A;}}
.pc-pill.pc-danger {{background:#FFF3F1; color:{DANGER};}}
.pc-pill.pc-muted {{background:#F0F3F7; color:#596A80;}}
.pc-notice {{display:flex; gap:10px; align-items:flex-start; border-radius:9px; padding:12px 16px;
  font-size:12.5px; line-height:1.6; margin:0 0 14px 0; border:1px solid;}}
.pc-notice.pc-warn {{background:#FFF9EA; border-color:#F8E2B5; color:#825510;}}
.pc-notice.pc-danger {{background:#FFF3F1; border-color:#F5C2BC; color:#912018;}}
.pc-notice.pc-info {{background:#F3F8FD; border-color:#D2E0F0; color:#2B4A6F;}}
.pc-notice.pc-muted {{background:#F5F7FA; border-color:var(--pc-border); color:#4E5F75;}}
.pc-table {{width:100%; border-collapse:collapse; font-size:12px; text-align:left;}}
.pc-table th {{color:var(--pc-muted); background:#F5F8FC; font-size:11px; font-weight:700; white-space:nowrap;}}
.pc-table th, .pc-table td {{padding:11px 10px; border-bottom:1px solid #E9EEF4;}}
.pc-table td.pc-num, .pc-table th.pc-num {{text-align:right; font-variant-numeric:tabular-nums;}}
.pc-feature h4 {{font-size:17px; font-weight:800; color:var(--pc-navy); margin:2px 0 6px 0;}}
.pc-feature p {{font-size:13px; color:#5B6C82; line-height:1.6; margin:0 0 10px 0;}}
.pc-bignum {{font-size:26px; font-weight:800; color:var(--pc-navy); line-height:1.2;}}
.pc-bignum-label {{font-size:12px; color:var(--pc-muted); margin-top:4px;}}
@media (max-width: 900px) {{ .pc-metrics {{grid-template-columns:repeat(2,minmax(0,1fr));}} }}
</style>
<span id="{THEME_MARKER}" style="display:none">{THEME_MARKER}</span>
"""


def apply_app_theme() -> None:
    """Inject the shared CSS once per page run (the entry script calls this before page.run())."""

    st.markdown(THEME_CSS, unsafe_allow_html=True)


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _tone(tone: str) -> str:
    return tone if tone in TONES else TONE_MUTED


def pill_html(text: str, tone: str = TONE_MUTED) -> str:
    return f'<span class="pc-pill pc-{_tone(tone)}">{esc(text)}</span>'


def chips_html(chips: Iterable[str]) -> str:
    """One row of small grey chips. Items are already-safe HTML fragments or plain text."""

    items = [f'<span class="pc-chip">{chip}</span>' for chip in chips if chip]
    if not items:
        return ""
    return '<div class="pc-chips">' + "".join(items) + "</div>"


def metric_card_html(label: str, value: str, sub: str = "", tone: str | None = None) -> str:
    dot = f'<span class="pc-dot pc-{_tone(tone)}"></span>' if tone else ""
    sub_html = f'<div class="pc-sub">{esc(sub)}</div>' if sub else ""
    return (
        f'<div class="pc-card pc-metric">{dot}<div class="pc-label">{esc(label)}</div>'
        f'<div class="pc-value">{esc(value)}</div>{sub_html}</div>'
    )


def metric_row_html(cards: Iterable[str]) -> str:
    return '<div class="pc-metrics">' + "".join(cards) + "</div>"


def notice_html(text_html: str, tone: str = TONE_WARN, icon: str = "!") -> str:
    """A full-width notice strip. ``text_html`` must already be escaped by the caller."""

    return f'<div class="pc-notice pc-{_tone(tone)}"><b>{esc(icon)}</b><div>{text_html}</div></div>'


def page_header_html(title: str, subtitle: str = "", eyebrow: str = "") -> str:
    parts = []
    if eyebrow:
        parts.append(f'<div class="pc-eyebrow pc-muted">{esc(eyebrow)}</div>')
    parts.append(f'<div class="pc-title">{esc(title)}</div>')
    if subtitle:
        parts.append(f'<div class="pc-subtitle">{esc(subtitle)}</div>')
    return "".join(parts)


def sidebar_brand_html() -> str:
    return f'<div class="pc-brand"><span class="pc-brandmark">✚</span>{esc(APP_NAME)}</div>'


def sidebar_group_html(label: str) -> str:
    return f'<div class="pc-navgroup">{esc(label)}</div>'
