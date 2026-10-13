"""Print how the stored news list clusters a 50-article sample, for the hand-judged evaluation.

Reads the stored list the app reads (local ``NEWS_RADAR_INDEX_PATH`` or R2), keeps title-matching
articles, takes the newest N or the N highest-ranked, clusters them with the production rules and
prints each issue with its members. The person judging compares the groups with what they read in
the titles and records only the counts (never the titles) in
``docs/NEWS_ISSUE_CLUSTER_EVAL_<date>.md``.

    PYTHONPATH=src python -m purchase_price.scripts.evaluate_news_issue_clusters --sample newest
    PYTHONPATH=src python -m purchase_price.scripts.evaluate_news_issue_clusters --sample importance
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime

from purchase_price.config import get_settings
from purchase_price.services import news_radar as radar
from purchase_price.services import news_radar_index as nri


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sample", choices=("newest", "importance"), default="newest")
    parser.add_argument("--size", type=int, default=50)
    args = parser.parse_args(argv)

    store = nri.resolve_store(get_settings())
    index = store.read_index() if store is not None else None
    if index is None:
        print("no stored list: set NEWS_RADAR_INDEX_PATH or the R2 read settings", file=sys.stderr)
        return 2

    groups = radar.load_keyword_groups()
    keywords = [keyword for group in groups for keyword in group.keywords]
    tiers = radar.load_source_tiers()
    ranked = [item for item in radar.rank_entries(index.items.values(), keywords, tiers) if item.relevant]
    if args.sample == "importance":
        ranked = radar.by_priority(ranked)
    sample = [item.entry for item in ranked[: args.size]]
    print(
        f"sample={args.sample} size={len(sample)} stored={len(index.items)} title-matching={len(ranked)} "
        f"generated={index.generated_at}"
    )

    issues = radar.cluster_news_issues(
        sample, keywords, tiers, now=datetime.now(UTC), roundup_terms=radar.load_issue_roundup_terms()
    )
    position = 0
    for issue in sorted(issues, key=lambda item: (-item.article_count, item.issue_id)):
        kind = "CLUSTER" if issue.article_count >= 2 else "single"
        print(f"\n[{kind} {issue.article_count}] {' · '.join(issue.group_names)}")
        for article_id in issue.article_ids:
            entry = index.items[article_id]
            position += 1
            print(
                f"  S{position:02d} {radar.seoul_time_text(entry.published_at)} "
                f"{entry.source_domain[:22]:22s} {entry.title[:70]}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
