"""매달 회계정보 공시 새 연도 확인.

    python -m purchase_price.scripts.check_khidi_new_year [--summary-json out.json]

Reads the fiscal-year choices on haspa.khidi.or.kr and the newest year in
``data/hospital_financial.csv``. When the site offers a newer year it prints the load commands,
writes ``new_year=<year>`` to ``$GITHUB_OUTPUT`` (the workflow then opens an issue) and, when
SMTP or webhook secrets exist, sends a short notice. It never changes data by itself: loading a
new year is reviewed in a pull request like every other data change.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Sequence
from pathlib import Path

import httpx

from purchase_price.services import khidi_financials as khidi
from purchase_price.services import news_alerts

_YEAR_OPTION = re.compile(r'<option value="(\d{4})"')


def site_years(html: str) -> list[int]:
    return sorted({int(y) for y in _YEAR_OPTION.findall(html)}, reverse=True)


def loaded_latest_year(csv_path: Path = khidi.DEFAULT_FINANCIAL_CSV) -> int | None:
    years = {row.fiscal_year for row in khidi.load_financial_csv(csv_path)}
    return max(years) if years else None


def notice_text(new_year: int, loaded: int | None) -> str:
    return "\n".join(
        [
            f"회계정보 공시(haspa.khidi.or.kr)에 {new_year}년 자료가 올라왔습니다. 지금 적재된 최신 연도는 {loaded}년입니다.",
            "적재 명령:",
            f"  python -m purchase_price.scripts.import_hospital_financials --fetch --years {new_year}",
            f"  python -m purchase_price.scripts.discover_size_peers --years {new_year}",
        ]
    )


def issue_markdown(new_year: int, loaded: int | None) -> str:
    return (
        f"haspa.khidi.or.kr에 {new_year}년 회계정보 공시가 올라왔습니다. 지금 적재된 최신 연도는 {loaded}년입니다.\n\n"
        "```bash\n"
        f"python -m purchase_price.scripts.import_hospital_financials --fetch --years {new_year}\n"
        f"python -m purchase_price.scripts.discover_size_peers --years {new_year}\n"
        "```\n\n"
        "적재 후 PR로 올리고 Benchmark 화면에서 새 연도가 선택되는지 확인합니다.\n"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", type=Path, default=khidi.DEFAULT_FINANCIAL_CSV)
    parser.add_argument("--summary-json", type=Path)
    args = parser.parse_args(argv)

    html = httpx.get(
        f"{khidi.HASPA_BASE_URL}/total-public-inq",
        params={"y": "", "hn": ""},
        headers={"User-Agent": "price-check-assistant hospital-benchmark monthly check"},
        timeout=30,
    ).text
    years = site_years(html)
    loaded = loaded_latest_year(args.csv)
    newest = years[0] if years else None
    new_year = newest if newest is not None and (loaded is None or newest > loaded) else None
    summary = {"site_years": years, "loaded_latest": loaded, "new_year": new_year, "notices": []}

    if new_year is not None:
        text = notice_text(new_year, loaded)
        print(text)
        env = os.environ
        subject = f"[병원 경영 Benchmark] {new_year}년 회계정보 공시가 올라왔습니다"
        summary["notices"] = [
            f"{r.channel} {r.status}"
            for r in (
                news_alerts.send_email(subject, text, env),
                news_alerts.send_webhook(f"{subject}\n{text}", env),
            )
        ]
        issue_body = Path("artifacts/khidi-new-year-issue.md")
        issue_body.parent.mkdir(parents=True, exist_ok=True)
        issue_body.write_text(issue_markdown(new_year, loaded), encoding="utf-8")
        output = os.getenv("GITHUB_OUTPUT")
        if output:
            with open(output, "a", encoding="utf-8") as handle:
                handle.write(f"new_year={new_year}\n")
    else:
        print(f"새 연도 없음: 사이트 최신 {newest}년, 적재된 최신 {loaded}년")

    step = os.getenv("GITHUB_STEP_SUMMARY")
    if step:
        with open(step, "a", encoding="utf-8") as handle:
            handle.write(
                "### 회계정보 공시 월간 확인\n\n"
                f"- 사이트 최신 연도: {newest}\n- 적재된 최신 연도: {loaded}\n"
                + (f"- **새 연도 {new_year}년 공개됨** — 이슈를 만들었습니다.\n" if new_year else "- 새 연도 없음\n")
            )
    if args.summary_json:
        args.summary_json.parent.mkdir(parents=True, exist_ok=True)
        args.summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
