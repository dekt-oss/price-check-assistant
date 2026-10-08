"""병원 경영·동향 리포트 만들기 (Phase 4 자동 리포트).

    python -m purchase_price.scripts.generate_hospital_report --hospital H-BUSAN-PAIK --peer region
    python -m purchase_price.scripts.generate_hospital_report --with-ai --with-news --r2

Writes ``<output-dir>/<name>.md`` and ``.xlsx``. ``--with-ai`` adds a paragraph from Claude built
only from computed numbers (skipped with a note when ANTHROPIC_API_KEY is missing or the answer
fails the number check). ``--with-news`` adds the last 7 days of News Radar titles and links.
``--r2`` also uploads both files under ``reports/v1/<date>/`` and removes report folders older
than 21 days, because a report with news titles is a NAVER display cache (21-day limit).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from purchase_price.config import Settings
from purchase_price.services import hospital_ai_explanation as ai
from purchase_price.services import hospital_benchmark as benchmark
from purchase_price.services import hospital_master as master_service
from purchase_price.services import hospital_report as report_service
from purchase_price.services import news_radar as radar

REPORT_PREFIX = "reports/v1"
REPORT_RETENTION_DAYS = 21


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hospital", default="H-BUSAN-PAIK")
    parser.add_argument(
        "--peer", action="append", choices=sorted(master_service.PEER_GROUP_LABELS), default=None,
        help="비교 방식 (여러 번 줄 수 있음). 기본: region, network",
    )
    parser.add_argument("--year", type=int, default=None, help="회계연도 (기본: 적재된 최신 연도)")
    parser.add_argument("--bed-range", default="700-850", help="유사 규모 비교군의 병상수 범위 (예: 700-850)")
    parser.add_argument("--output-dir", default="artifacts/hospital-report")
    parser.add_argument("--with-ai", action="store_true")
    parser.add_argument("--with-news", action="store_true")
    parser.add_argument("--r2", action="store_true")
    parser.add_argument("--summary-json", default=None)
    return parser


def _explanation_for(report: report_service.BenchmarkReport) -> tuple[str | None, str]:
    key = ai.resolve_api_key()
    if not key:
        return None, "AI 설명: 연결 설정(ANTHROPIC_API_KEY)이 없어 계산 문장만 실었습니다."
    source = ai.build_input(
        target_name=report.target.short_name,
        fiscal_year=report.fiscal_year,
        peer_label=report.peer_label,
        peer_names=[p.short_name for p in report.peers],
        rows=report.rows,
        findings=report.findings,
        quality_notes=report.quality,
    )
    try:
        result = ai.explain(source, api_key=key)
    except ai.ExplanationError as exc:
        return None, f"AI 설명을 싣지 못했습니다: {exc}"
    return result.text, f"AI 설명({result.model}): 위 표의 계산 결과만 입력으로 받아 쓴 문장이며, 숫자는 모두 계산 결과와 대조했습니다."


def _news(settings: Settings) -> list[report_service.NewsLine]:
    from purchase_price.services import news_radar_index as news_index

    store = news_index.resolve_store(settings)
    if store is None:
        return []
    index = store.read_index()
    if index is None:
        return []
    return report_service.news_lines(
        index.items.values(),
        report_service.keywords_in_groups(),
        now=datetime.now().astimezone(radar.SEOUL),
    )


def _upload(settings: Settings, files: list[Path], day: str) -> list[str]:
    from purchase_price.services.news_radar_index import R2NewsRadarStore

    store = R2NewsRadarStore.from_settings(settings)
    client, bucket = store._client, store.bucket  # same R2 writer the News Radar job uses
    keys: list[str] = []
    for path in files:
        key = f"{REPORT_PREFIX}/{day}/{path.name}"
        content_type = (
            "text/markdown; charset=utf-8"
            if path.suffix == ".md"
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        client.put_object(Bucket=bucket, Key=key, Body=path.read_bytes(), ContentType=content_type)
        keys.append(key)
    cutoff = (datetime.now().astimezone(radar.SEOUL) - timedelta(days=REPORT_RETENTION_DAYS)).date().isoformat()
    token = None
    while True:
        kwargs = {"Bucket": bucket, "Prefix": f"{REPORT_PREFIX}/"}
        if token:
            kwargs["ContinuationToken"] = token
        response = client.list_objects_v2(**kwargs)
        for obj in response.get("Contents", []) or []:
            parts = str(obj["Key"]).split("/")
            if len(parts) >= 3 and parts[2] < cutoff:
                client.delete_object(Bucket=bucket, Key=obj["Key"])
        if not response.get("IsTruncated"):
            break
        token = response.get("NextContinuationToken")
    return keys


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = Settings()
    data = benchmark.load_benchmark_data()
    target = data.master.get(args.hospital)
    if target is None:
        print(f"병원 명단에 없는 병원입니다: {args.hospital}", file=sys.stderr)
        return 2
    year = args.year or (data.years_for(target.hospital_id) or [None])[-1]
    if year is None:
        print(f"{target.short_name}의 회계자료가 없습니다.", file=sys.stderr)
        return 2

    news = _news(settings) if args.with_news else []
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now().astimezone(radar.SEOUL)
    written: list[Path] = []
    summaries: list[dict[str, object]] = []
    for peer_kind in args.peer or ["region", "network"]:
        low, high = (int(v) for v in args.bed_range.split("-", 1))
        report = report_service.build_report(data, target, peer_kind, year, bed_range=(low, high), now=now)
        if args.with_ai:
            report.explanation, report.explanation_note = _explanation_for(report)
        report.news = news
        md_path = out_dir / report_service.report_filename(report, "md")
        xlsx_path = out_dir / report_service.report_filename(report, "xlsx")
        md_path.write_text(report_service.report_markdown(report), encoding="utf-8")
        xlsx_path.write_bytes(report_service.report_workbook(report))
        written += [md_path, xlsx_path]
        summaries.append(
            {
                "peer": report.peer_label,
                "peers": [p.short_name for p in report.peers],
                "findings": len(report.findings),
                "ai": bool(report.explanation),
                "ai_note": report.explanation_note,
                "news": len(report.news),
                "markdown": str(md_path),
                "excel": str(xlsx_path),
            }
        )

    uploaded = _upload(settings, written, now.date().isoformat()) if args.r2 else []
    summary = {"hospital": target.short_name, "fiscal_year": year, "reports": summaries, "uploaded": uploaded}
    text = json.dumps(summary, ensure_ascii=False, indent=2)
    print(text)
    if args.summary_json:
        Path(args.summary_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.summary_json).write_text(text, encoding="utf-8")
    step_summary = os.getenv("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as handle:
            for path in written:
                if path.suffix == ".md":
                    handle.write(path.read_text(encoding="utf-8") + "\n\n---\n\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
