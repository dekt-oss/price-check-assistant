from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from purchase_price.clients.data_go_kr import PublicDataPortalClient
from purchase_price.schemas import CollectedPrice, ProductQuery
from purchase_price.services.g2b_adaptive_search import search_mapped_g2b_candidates_adaptive
from purchase_price.services.g2b_product_mapping import (
    G2BProductMapping,
    resolve_verified_g2b_mapping,
)

from .base import CollectorSkipped, PriceCollector
from .g2b_shopping import G2B_SHOPPING_BASE_URL, SOURCE_NAME, G2BShoppingCollector


@dataclass(frozen=True)
class G2BSearchTelemetry:
    request_count: int
    request_budget: int
    window_count: int
    pages_fetched: int
    records_seen: int
    begin_date: date
    end_date: date


class VerifiedG2BShoppingSearchCollector(PriceCollector):
    """User-facing G2B adapter restricted to explicitly verified exact-model mappings."""

    name = SOURCE_NAME

    def __init__(
        self,
        service_key: str | None = None,
        *,
        collector: G2BShoppingCollector | None = None,
        mappings: tuple[G2BProductMapping, ...] | None = None,
        lookback_days: int = 365,
        end_date: date | None = None,
        base_url: str = G2B_SHOPPING_BASE_URL,
        timeout_seconds: float = 20.0,
        max_retries: int = 3,
        num_of_rows: int = 100,
        max_pages: int = 20,
        max_split_depth: int = 12,
        request_budget: int = 120,
    ) -> None:
        if lookback_days < 1:
            raise ValueError("lookback_days must be positive")
        if num_of_rows < 1:
            raise ValueError("num_of_rows must be positive")
        if max_pages < 1:
            raise ValueError("max_pages must be positive")
        if request_budget < 1:
            raise ValueError("request_budget must be positive")

        if collector is None:
            if not service_key or not service_key.strip():
                raise ValueError("DATA_GO_KR_SERVICE_KEY is required for live G2B search")
            client = PublicDataPortalClient(
                service_key,
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
            )
            collector = G2BShoppingCollector(service_key, base_url=base_url, client=client)

        self.collector = collector
        self.mappings = mappings
        self.lookback_days = lookback_days
        self.end_date = end_date
        self.num_of_rows = num_of_rows
        self.max_pages = max_pages
        self.max_split_depth = max_split_depth
        self.request_budget = request_budget
        self.last_telemetry: G2BSearchTelemetry | None = None

    def search(self, query: ProductQuery) -> list[CollectedPrice]:
        self.last_telemetry = None
        model_name = query.model_name.strip()
        if not model_name:
            raise CollectorSkipped(
                "exact 모델명이 없어 검증된 나라장터 세부품명 mapping을 선택할 수 없음"
            )

        mapping = resolve_verified_g2b_mapping(query, self.mappings)
        if mapping is None:
            raise CollectorSkipped(
                f"모델 {model_name!r}의 검증된 나라장터 세부품명 mapping이 없어 직접가격 API를 호출하지 않음"
            )

        end_date = self.end_date or date.today()
        begin_date = end_date - timedelta(days=self.lookback_days - 1)
        result = search_mapped_g2b_candidates_adaptive(
            self.collector,
            query,
            begin_date=begin_date,
            end_date=end_date,
            mappings=(mapping,),
            num_of_rows=self.num_of_rows,
            max_pages=self.max_pages,
            max_split_depth=self.max_split_depth,
            request_budget=self.request_budget,
        )
        self.last_telemetry = G2BSearchTelemetry(
            request_count=result.request_count,
            request_budget=result.request_budget,
            window_count=len(result.windows),
            pages_fetched=result.pages_fetched,
            records_seen=result.records_seen,
            begin_date=begin_date,
            end_date=end_date,
        )
        return list(result.candidate_prices)
