from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from purchase_price.config import Settings
from purchase_price.schemas import ProductQuery
from purchase_price.services import track_b_r2_quote_index as legacy_track_b_r2
from purchase_price.storage.r2 import R2ConfigurationError, R2IntegrityError


@dataclass
class TrackBServingSnapshot:
    """Hot-reload-safe serving snapshot for one Workspace search.

    Streamlit Cloud can retain an older already-imported track_b_r2_quote_index module
    during a code hot reload. This adapter avoids importing newly-added symbols directly
    from that stale module while preserving the single-pointer / single-session contract.
    """

    status: str
    path: Path | None = None
    engine: Engine | None = None
    session: Session | None = None

    def __enter__(self) -> TrackBServingSnapshot:
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self.close()

    def close(self) -> None:
        if self.session is not None:
            self.session.close()
            self.session = None
        if self.engine is not None:
            self.engine.dispose()
            self.engine = None

    def lookup(self, query: ProductQuery, *, quote_unit_price: Any):
        from purchase_price.services.track_b_db_quote_comparison import (
            TrackBQuoteComparison,
            compare_track_b_quote,
        )
        from purchase_price.services.track_b_reference_quality import (
            refine_track_b_reference_quality,
        )

        if self.status in {"unavailable", "not_ingested"} or self.session is None:
            return TrackBQuoteComparison(self.status, (), 0)

        result = compare_track_b_quote(
            self.session,
            query,
            quote_unit_price=quote_unit_price,
        )
        return refine_track_b_reference_quality(self.session, query, result)

    def lookup_model_summaries(
        self,
        queries: tuple[ProductQuery, ...],
        *,
        quote_unit_prices: tuple[Any, ...] | None = None,
        limit_per_model: int = 50,
    ):
        from purchase_price.services import track_b_db_quote_comparison as track_b_db

        queries = tuple(queries)
        comparison_type = track_b_db.TrackBQuoteComparison
        if self.status in {"unavailable", "not_ingested"} or self.session is None:
            return tuple(comparison_type(self.status, (), 0) for _ in queries)
        prices = (
            tuple(quote_unit_prices)
            if quote_unit_prices is not None
            else tuple(None for _ in queries)
        )
        if len(prices) != len(queries):
            raise ValueError("quote_unit_prices must align with queries")

        native_batch = getattr(track_b_db, "compare_track_b_models_batch", None)
        if callable(native_batch):
            return native_batch(
                self.session,
                queries,
                quote_unit_prices=prices,
                limit_per_model=limit_per_model,
            )

        # Streamlit Cloud may retain the pre-batch module object across a hot reload.
        # Preserve correctness with the legacy strict comparator rather than failing the
        # entire Workspace. This compatibility path is temporary and intentionally
        # sacrifices batch performance only while the stale module remains resident.
        return tuple(
            track_b_db.compare_track_b_quote(
                self.session,
                query,
                quote_unit_price=quote_unit_price,
                limit=limit_per_model,
            )
            for query, quote_unit_price in zip(queries, prices, strict=True)
        )


def _native_snapshot_opener():
    """Return a native opener only when the currently loaded module exposes it."""

    opener = getattr(legacy_track_b_r2, "open_track_b_serving_snapshot", None)
    return opener if callable(opener) else None


def open_track_b_serving_snapshot(
    *,
    settings: Settings | None = None,
):
    """Open one Track B serving snapshot without requiring a fresh module reload."""

    settings = settings or Settings()
    native = _native_snapshot_opener()
    if native is not None:
        return native(settings=settings)

    if not settings.r2_configured:
        return TrackBServingSnapshot("unavailable")

    local_index_path = getattr(legacy_track_b_r2, "_local_index_path", None)
    if not callable(local_index_path):
        return TrackBServingSnapshot("unavailable")

    try:
        path = local_index_path(settings)
        if path is None:
            return TrackBServingSnapshot("not_ingested")
        engine = create_engine(
            f"sqlite+pysqlite:///{path}",
            connect_args={"check_same_thread": False},
        )
        return TrackBServingSnapshot(
            status="available",
            path=path,
            engine=engine,
            session=Session(bind=engine, autoflush=False, expire_on_commit=False),
        )
    except (
        BotoCoreError,
        ClientError,
        OSError,
        SQLAlchemyError,
        R2ConfigurationError,
        R2IntegrityError,
        ValueError,
    ):
        return TrackBServingSnapshot("unavailable")
