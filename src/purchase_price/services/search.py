from dataclasses import dataclass, field

from purchase_price.collectors.base import PriceCollector
from purchase_price.schemas import CollectedPrice, ProductQuery


@dataclass(frozen=True)
class SourceRunStatus:
    source_name: str
    succeeded: bool
    result_count: int
    error: str | None = None

    @property
    def status_label(self) -> str:
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


def search_all(query: ProductQuery, collectors: list[PriceCollector]) -> SearchRun:
    run = SearchRun()
    for collector in collectors:
        try:
            results = collector.search(query)
        except Exception as exc:  # collector isolation is intentional
            error = f"{collector.name}: {exc}"
            run.errors.append(error)
            run.source_statuses.append(
                SourceRunStatus(
                    source_name=collector.name,
                    succeeded=False,
                    result_count=0,
                    error=str(exc),
                )
            )
            continue

        run.results.extend(results)
        run.source_statuses.append(
            SourceRunStatus(
                source_name=collector.name,
                succeeded=True,
                result_count=len(results),
            )
        )
    return run
