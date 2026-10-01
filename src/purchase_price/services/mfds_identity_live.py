from __future__ import annotations

from typing import Any, Protocol

from purchase_price.clients.data_go_kr import PublicDataClientError, PublicDataPortalClient
from purchase_price.config import Settings
from purchase_price.services.matching import exact_model_match
from purchase_price.services.mfds_device_intelligence import unwrap_mfds_page
from purchase_price.services.mfds_identity_index import (
    MFDS_PRODUCT_INFO_BASE_URL,
    MFDS_PRODUCT_INFO_OPERATION,
    MfdsIdentityLookup,
    parse_mfds_product_info_record,
)


class _JsonClient(Protocol):
    def get_json(self, base_url: str, endpoint: str, **params: Any) -> dict[str, Any]: ...


def lookup_mfds_model_identity_live(
    model_name: str,
    *,
    settings: Settings | None = None,
    client: _JsonClient | None = None,
    max_pages: int = 3,
    num_of_rows: int = 100,
) -> MfdsIdentityLookup:
    """Resolve an exact model against the approved MFDS standard-code product API.

    Production live probing confirmed that MdeqStdCdPrdtInfoService03 accepts FOML_INFO while the
    legacy MdeqModlInfoService01 service is not authorized for the current key. This fallback is
    therefore used only for exact model identity and never for fuzzy matching or active/inactive
    product-state inference.
    """

    model = str(model_name or "").strip()
    if not model:
        return MfdsIdentityLookup("empty", model, None, ())
    if max_pages < 1 or num_of_rows < 1:
        raise ValueError("page bounds must be positive")

    settings = settings or Settings()
    service_key = (settings.resolved_mfds_service_key or "").strip()
    if client is None and not service_key:
        return MfdsIdentityLookup("unavailable", model, None, ())

    active_client = client or PublicDataPortalClient(
        service_key,
        timeout_seconds=settings.mfds_request_timeout_seconds,
        max_retries=settings.mfds_max_retries,
    )

    records = []
    try:
        fetched = 0
        for page_no in range(1, max_pages + 1):
            payload = active_client.get_json(
                settings.mfds_product_info_base_url or MFDS_PRODUCT_INFO_BASE_URL,
                MFDS_PRODUCT_INFO_OPERATION,
                FOML_INFO=model,
                pageNo=page_no,
                numOfRows=num_of_rows,
            )
            page = unwrap_mfds_page(payload)
            fetched += len(page.items)
            records.extend(
                parse_mfds_product_info_record(item)
                for item in page.items
                if exact_model_match(model, item.get("FOML_INFO"))
            )
            if not page.items:
                break
            if page.total_count is not None and fetched >= page.total_count:
                break
            if len(page.items) < num_of_rows:
                break
    except (PublicDataClientError, ValueError):
        return MfdsIdentityLookup("unavailable", model, None, ())

    deduped = {}
    for record in records:
        key = (
            record.udi_di or "",
            record.permit_number or "",
            record.model_name or "",
            record.registered_company or "",
            record.product_name or "",
        )
        deduped.setdefault(key, record)

    resolved = tuple(deduped.values())
    return MfdsIdentityLookup(
        "success" if resolved else "success_0",
        model,
        "model" if resolved else None,
        resolved,
    )
