from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from purchase_price.clients.data_go_kr import PublicDataClientError
from purchase_price.config import Settings
from purchase_price.schemas import ProductQuery
from purchase_price.services.g2b_product_mapping import resolve_verified_g2b_mapping
from purchase_price.services.mfds_device_intelligence import (
    MFDS_BUSINESS_LICENSE_BASE_URL,
    MFDS_MODEL_INFO_BASE_URL,
    MedicalDeviceBusinessRecord,
    MedicalDeviceModelRecord,
    MfdsBusinessLicenseClient,
    MfdsModelInfoClient,
    resolve_exact_model_identity,
)
from purchase_price.ui.track_b_transactions import (
    comparison_candidates,
    reference_candidates,
)


@dataclass(frozen=True)
class MfdsWorkspaceResult:
    status: str
    product_name: str
    model_name: str
    queried: bool
    records: tuple[MedicalDeviceModelRecord, ...] = ()
    active_records: tuple[MedicalDeviceModelRecord, ...] = ()
    exact_records: tuple[MedicalDeviceModelRecord, ...] = ()
    exact_confirmed: bool = False
    exact_ambiguous: bool = False
    business_records: tuple[MedicalDeviceBusinessRecord, ...] = ()
    business_query: str | None = None
    registered_company_status: str = "company_source_not_connected"
    error_type: str | None = None
    error_message: str | None = None

    @property
    def active_competitor_records(self) -> tuple[MedicalDeviceModelRecord, ...]:
        exact_ids = {
            (record.permit_number or "", record.model_name or "")
            for record in self.exact_records
        }
        return tuple(
            record
            for record in self.active_records
            if (record.permit_number or "", record.model_name or "") not in exact_ids
        )

    @property
    def permit_numbers(self) -> tuple[str, ...]:
        values = {
            record.permit_number.strip()
            for record in self.exact_records
            if record.permit_number and record.permit_number.strip()
        }
        return tuple(sorted(values))

    @property
    def industry_types(self) -> tuple[str, ...]:
        values = {
            record.industry_type.strip()
            for record in self.records
            if record.industry_type and record.industry_type.strip()
        }
        return tuple(sorted(values))


def _candidate_detail_codes(track_b: Any) -> set[str]:
    codes: set[str] = set()
    for candidate in (*comparison_candidates(track_b), *reference_candidates(track_b)):
        code = str(getattr(candidate, "detail_code", "") or "").strip()
        if code:
            codes.add(code)
    return codes


def should_query_mfds(query: ProductQuery, track_b: Any) -> bool:
    """Use evidence-backed classification only to decide whether MFDS lookup is relevant.

    This gate does not establish an MFDS identity. Exact identity still requires the official
    product-name result plus exact normalized model matching.
    """

    if any(code.startswith("42") for code in _candidate_detail_codes(track_b)):
        return True

    mapping = resolve_verified_g2b_mapping(query)
    return bool(
        mapping
        and mapping.detail_product_code
        and mapping.detail_product_code.startswith("42")
    )


def research_mfds_for_workspace(
    query: ProductQuery,
    track_b: Any,
    *,
    settings: Settings | None = None,
    model_client: MfdsModelInfoClient | None = None,
    business_client: MfdsBusinessLicenseClient | None = None,
) -> MfdsWorkspaceResult:
    product_name = (query.product_name or "").strip()
    model_name = (query.model_name or "").strip()
    if not product_name or not should_query_mfds(query, track_b):
        return MfdsWorkspaceResult(
            status="not_applicable",
            product_name=product_name,
            model_name=model_name,
            queried=False,
        )

    settings = settings or Settings()
    service_key = (settings.resolved_mfds_service_key or "").strip()
    if model_client is None and not service_key:
        return MfdsWorkspaceResult(
            status="not_configured",
            product_name=product_name,
            model_name=model_name,
            queried=False,
        )

    model_client = model_client or MfdsModelInfoClient(
        service_key,
        base_url=settings.mfds_model_info_base_url or MFDS_MODEL_INFO_BASE_URL,
        timeout_seconds=settings.mfds_request_timeout_seconds,
        max_retries=settings.mfds_max_retries,
    )

    try:
        records = model_client.search_models(product_name, max_pages=5)
        active = tuple(record for record in records if record.active_for_domestic_candidate)
        resolution = resolve_exact_model_identity(records, model_name) if model_name else None

        manufacturer = (query.manufacturer or "").strip()
        businesses: tuple[MedicalDeviceBusinessRecord, ...] = ()
        if manufacturer:
            if business_client is None and service_key:
                business_client = MfdsBusinessLicenseClient(
                    service_key,
                    base_url=(
                        settings.mfds_business_license_base_url
                        or MFDS_BUSINESS_LICENSE_BASE_URL
                    ),
                    timeout_seconds=settings.mfds_request_timeout_seconds,
                    max_retries=settings.mfds_max_retries,
                )
            if business_client is not None:
                businesses = business_client.search_company(manufacturer)

        return MfdsWorkspaceResult(
            status="success" if records else "success_0",
            product_name=product_name,
            model_name=model_name,
            queried=True,
            records=records,
            active_records=active,
            exact_records=resolution.exact_matches if resolution is not None else (),
            exact_confirmed=bool(resolution and resolution.confirmed),
            exact_ambiguous=bool(resolution and resolution.ambiguous),
            business_records=businesses,
            business_query=manufacturer or None,
        )
    except (PublicDataClientError, ValueError) as exc:
        return MfdsWorkspaceResult(
            status="failure",
            product_name=product_name,
            model_name=model_name,
            queried=True,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
