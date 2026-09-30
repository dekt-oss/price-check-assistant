from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from purchase_price.clients.data_go_kr import (
    PublicDataClientError,
    PublicDataPortalClient,
)
from purchase_price.config import Settings
from purchase_price.services.matching import exact_model_match, normalize_text
from purchase_price.services.mfds_device_intelligence import unwrap_mfds_page

MFDS_RECALL_BASE_URL = (
    "https://apis.data.go.kr/1471000/MdlpRtrvlSleStpgeInfoService04"
)
MFDS_RECALL_MODEL_OPERATION = "getTypeNameList04"
MFDS_RECALL_PRODUCT_OPERATION = "getItemNameList04"
MFDS_RECALL_SOURCE_URL = "https://www.data.go.kr/data/15056785/openapi.do"


class _JsonClient(Protocol):
    def get_json(self, base_url: str, endpoint: str, **params: Any) -> dict[str, Any]: ...


@dataclass(frozen=True)
class MfdsRecallRecord:
    recall_item_seq: str | None
    model_name: str | None
    product_name: str | None
    classification_no: str | None
    classification_name: str | None
    grade: str | None
    manufacturer_name: str | None
    report_state_code: str | None
    report_state_name: str | None
    report_submit_date: str | None
    report_kind_code: str | None
    report_kind_name: str | None
    reason: str | None
    pack_unit: str | None
    valid_term: str | None


@dataclass(frozen=True)
class MfdsRecallLookupResult:
    status: str
    query_type: str
    query: str
    records: tuple[MfdsRecallRecord, ...] = ()
    error_type: str | None = None
    error_message: str | None = None
    source_url: str = MFDS_RECALL_SOURCE_URL
    checked_at: str | None = None

    @property
    def checked(self) -> bool:
        return self.status in {"success", "success_0"}


def _checked_at() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat()


def _text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def parse_model_recall_record(record: Mapping[str, Any]) -> MfdsRecallRecord:
    return MfdsRecallRecord(
        recall_item_seq=_text(record.get("RECALL_ITEM_SEQ")),
        model_name=_text(record.get("TYPE_NAME")),
        product_name=None,
        classification_no=_text(record.get("MEA_CLASS_NO")),
        classification_name=_text(record.get("MEA_CLASS_NAME")),
        grade=_text(record.get("GRADE")),
        manufacturer_name=_text(record.get("MANUF_NAME")),
        report_state_code=_text(record.get("REPORT_STATE_CODE")),
        report_state_name=_text(record.get("REPORT_STATE_NAME")),
        report_submit_date=_text(record.get("REPORT_SUBMIT_DATE")),
        report_kind_code=_text(record.get("REPORT_KIND_CODE")),
        report_kind_name=_text(record.get("REPORT_KIND_NAME")),
        reason=_text(record.get("RTRVL_RESN_CN")),
        pack_unit=_text(record.get("PACK_UNIT")),
        valid_term=_text(record.get("VALID_TERM")),
    )


def parse_product_recall_record(record: Mapping[str, Any]) -> MfdsRecallRecord:
    return MfdsRecallRecord(
        recall_item_seq=_text(record.get("RECALL_ITEM_SEQ")),
        model_name=None,
        product_name=_text(record.get("ITEM_NAME")),
        classification_no=_text(record.get("MEA_CLASS_NO")),
        classification_name=_text(record.get("MEA_CLASS_NAME")),
        grade=_text(record.get("GRADE")),
        manufacturer_name=None,
        report_state_code=_text(record.get("REPORT_STATE_CODE")),
        report_state_name=_text(record.get("REPORT_STATE_NAME")),
        report_submit_date=_text(record.get("REPORT_SUBMIT_DATE")),
        report_kind_code=_text(record.get("REPORT_KIND_CODE")),
        report_kind_name=_text(record.get("REPORT_KIND_NAME")),
        reason=_text(record.get("RTRVL_RESN_CN")),
        pack_unit=_text(record.get("PACK_UNIT")),
        valid_term=_text(record.get("VALID_TERM")),
    )


def is_mfds_recall_authorization_error(exc: Exception) -> bool:
    text = str(exc).upper()
    return any(
        marker in text
        for marker in (
            "SERVICE_KEY_IS_NOT_REGISTERED_ERROR",
            "SERVICE_ACCESS_DENIED_ERROR",
            "PERMISSION_DENIED",
            "CODE=30",
        )
    )


class MfdsRecallClient:
    """Official MFDS medical-device recall/sale-stop adapter.

    The current Service04 contract exposes model-name and product-name operations but does not
    expose an exact MFDS permit-number field in those response schemas. Positive model/product
    matches therefore remain related official safety evidence rather than being promoted to an
    exact RED product match by this adapter alone.
    """

    def __init__(
        self,
        service_key: str,
        *,
        base_url: str = MFDS_RECALL_BASE_URL,
        client: _JsonClient | None = None,
        timeout_seconds: float = 20.0,
        max_retries: int = 3,
    ) -> None:
        self.base_url = base_url
        self.client = client or PublicDataPortalClient(
            service_key,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )

    def search_model(
        self,
        model_name: str,
        *,
        max_pages: int = 3,
        num_of_rows: int = 100,
    ) -> tuple[MfdsRecallRecord, ...]:
        query = model_name.strip()
        if not query:
            raise ValueError("model_name is required for MFDS recall model lookup")

        records: list[MfdsRecallRecord] = []
        for page_no in range(1, max_pages + 1):
            payload = self.client.get_json(
                self.base_url,
                MFDS_RECALL_MODEL_OPERATION,
                type_name=query,
                pageNo=page_no,
                numOfRows=num_of_rows,
            )
            page = unwrap_mfds_page(payload)
            records.extend(parse_model_recall_record(item) for item in page.items)
            if not page.items:
                break
            if page.total_count is not None and page_no * num_of_rows >= page.total_count:
                break
            if len(page.items) < num_of_rows:
                break

        return tuple(
            record
            for record in records
            if exact_model_match(query, record.model_name)
        )

    def search_product(
        self,
        product_name: str,
        *,
        max_pages: int = 3,
        num_of_rows: int = 100,
    ) -> tuple[MfdsRecallRecord, ...]:
        query = product_name.strip()
        if not query:
            raise ValueError("product_name is required for MFDS recall product lookup")

        query_key = normalize_text(query)
        records: list[MfdsRecallRecord] = []
        for page_no in range(1, max_pages + 1):
            payload = self.client.get_json(
                self.base_url,
                MFDS_RECALL_PRODUCT_OPERATION,
                item_name=query,
                pageNo=page_no,
                numOfRows=num_of_rows,
            )
            page = unwrap_mfds_page(payload)
            records.extend(parse_product_recall_record(item) for item in page.items)
            if not page.items:
                break
            if page.total_count is not None and page_no * num_of_rows >= page.total_count:
                break
            if len(page.items) < num_of_rows:
                break

        return tuple(
            record
            for record in records
            if normalize_text(record.product_name) == query_key
        )


def lookup_mfds_recall(
    *,
    model_name: str = "",
    product_name: str = "",
    settings: Settings | None = None,
    client: MfdsRecallClient | None = None,
) -> MfdsRecallLookupResult:
    model = model_name.strip()
    product = product_name.strip()
    if not model and not product:
        return MfdsRecallLookupResult(status="not_run", query_type="", query="")

    query_type = "model" if model else "product"
    query = model or product
    settings = settings or Settings()
    raw_settings = getattr(settings, "__dict__", {})
    if not isinstance(raw_settings, dict):
        raw_settings = {}
    service_key = str(
        raw_settings.get("mfds_recall_service_key")
        or raw_settings.get("mfds_service_key")
        or raw_settings.get("data_go_kr_market_service_key")
        or raw_settings.get("data_go_kr_service_key")
        or ""
    ).strip()
    if client is None and not service_key:
        return MfdsRecallLookupResult(
            status="not_configured",
            query_type=query_type,
            query=query,
        )

    client = client or MfdsRecallClient(
        service_key,
        base_url=raw_settings.get("mfds_recall_base_url") or MFDS_RECALL_BASE_URL,
        timeout_seconds=settings.mfds_request_timeout_seconds,
        max_retries=settings.mfds_max_retries,
    )
    try:
        records = (
            client.search_model(model)
            if model
            else client.search_product(product)
        )
    except PublicDataClientError as exc:
        return MfdsRecallLookupResult(
            status=(
                "not_authorized"
                if is_mfds_recall_authorization_error(exc)
                else "failure"
            ),
            query_type=query_type,
            query=query,
            error_type=type(exc).__name__,
            error_message=str(exc),
            checked_at=_checked_at(),
        )
    except ValueError as exc:
        return MfdsRecallLookupResult(
            status="failure",
            query_type=query_type,
            query=query,
            error_type=type(exc).__name__,
            error_message=str(exc),
            checked_at=_checked_at(),
        )

    return MfdsRecallLookupResult(
        status="success" if records else "success_0",
        query_type=query_type,
        query=query,
        records=records,
        checked_at=_checked_at(),
    )
