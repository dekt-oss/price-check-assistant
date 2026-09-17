# Production unified-search crash — 2026-09-17

## Symptom

Production unified search raised `AttributeError` in `pages/1_대시보드.py` while rendering `track_b.reference_candidates` after submitting `DFM100`.

## Root cause

The newly deployed page assumed the latest `TrackBQuoteComparison` dataclass shape. During Streamlit Cloud rolling reload, the page module could be refreshed while the imported service module still exposed an older comparison object without `reference_candidates` and without some later transaction metadata fields.

CI exercised a clean single-version process and therefore did not reproduce this mixed-version runtime state. The existing Production Browser Smoke also targeted the old `빠른 검색` navigation and did not submit the new `통합 검색` form, so it did not cover the failing path.

## Fix

- Render strict/reference candidates through compatibility helpers using defensive `getattr` access.
- Treat missing `reference_candidates` as an empty Research-only list rather than crashing the page.
- Render optional supplier/demand/date/quantity/unit metadata defensively during rolling deploys.
- Extend Production Browser Smoke to use the current `통합 검색` UI.
- On post-merge Production runs, submit `DFM100` and require a rendered transaction dataframe plus the expected `검색 참고 2건` summary.
- Add unit coverage for legacy comparison objects without `reference_candidates`.

## Acceptance

A fix is not considered complete until the post-merge Production Browser Smoke succeeds against the deployed Streamlit app and the DFM100 unified-search result renders without an exception.
