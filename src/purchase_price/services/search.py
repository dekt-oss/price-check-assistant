from dataclasses import dataclass, field
from typing import Any

from purchase_price.collectors.base import CollectorSkipped, PriceCollector
from purchase_price.schemas import CollectedPrice, ProductQuery


@dataclass(frozen=True)
class SourceRunStatus:
    source_name: str
    succeeded: bool
    result_count: int
    error: str | None = None
    skipped: bool = False
    note: str | None = None
    telemetry: dict[str, Any] | None = None

    @property
    def status_label(self) -> str:
        if self.skipped:
            return "미검색"
        if not self.succeeded:
            return "실패"
        if self.result_count == 0:
            return "성공 · 0건"
        return f"성공 · {self.result_count}건"


@dataclass
class SearchRun:
    results: list[CollectedPrice] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    source_statuses: list[SourceRunStatus] = field(default_factory=list)


def _collector_telemetry(collector: PriceCollector) -> dict[str, Any] | None:
    telemetry = getattr(collector, "last_telemetry", None)
    if telemetry is None:
        return None
    fields = (
        "request_count",
        "request_budget",
        "window_count",
        "pages_fetched",
        "records_seen",
        "begin_date",
        "end_date",
    )
    output: dict[str, Any] = {}
    for name in fields:
        value = getattr(telemetry, name, None)
        if value is not None:
            output[name] = value.isoformat() if hasattr(value, "isoformat") else value
    return output or None


def search_all(query: ProductQuery, collectors: list[PriceCollector]) -> SearchRun:
    run = SearchRun()
    for collector in collectors:
        try:
            results = collector.search(query)
        except CollectorSkipped as exc:
            run.source_statuses.append(
                SourceRunStatus(
                    source_name=collector.name,
                    succeeded=False,
                    result_count=0,
                    skipped=True,
                    note=str(exc),
                    telemetry=_collector_telemetry(collector),
                )
            )
            continue
        except Exception as exc:  # collector isolation is intentional
            error = f"{collector.name}: {exc}"
            run.errors.append(error)
            run.source_statuses.append(
                SourceRunStatus(
                    source_name=collector.name,
                    succeeded=False,
                    result_count=0,
                    error=str(exc),
                    telemetry=_collector_telemetry(collector),
                )
            )
            continue

        run.results.extend(results)
        run.source_statuses.append(
            SourceRunStatus(
                source_name=collector.name,
                succeeded=True,
                result_count=len(results),
                telemetry=_collector_telemetry(collector),
            )
        )
    return run
