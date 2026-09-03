from dataclasses import dataclass, field

from purchase_price.collectors.base import PriceCollector
from purchase_price.schemas import CollectedPrice, ProductQuery


@dataclass
class SearchRun:
    results: list[CollectedPrice] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def search_all(query: ProductQuery, collectors: list[PriceCollector]) -> SearchRun:
    run = SearchRun()
    for collector in collectors:
        try:
            run.results.extend(collector.search(query))
        except Exception as exc:  # collector isolation is intentional
            run.errors.append(f"{collector.name}: {exc}")
    return run
