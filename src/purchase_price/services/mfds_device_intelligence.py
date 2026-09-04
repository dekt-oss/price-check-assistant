from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from purchase_price.clients.data_go_kr import (
    SUCCESS_RESULT_CODES,
    PublicDataClientError,
    PublicDataPortalClient,
)
from purchase_price.services.matching import exact_model_match

MFDS_MODEL_INFO_BASE_URL = "https://apis.data.go.kr/1471000/MdeqModlInfoService01"
MFDS_MODEL_INFO_OPERATION = "getMdeqModlInq01"
MFDS_BUSINESS_LICENSE_BASE_URL = (
    "https://apis.data.go.kr/1471000/MdlpMnfcturPrmisnInfoService01"
)
MFDS_BUSINESS_LICENSE_OPERATION = "getMdlpMnfcturPrmisnList01"


@dataclass(frozen=True)
class MfdsPage:
    items: tuple[dict[str, Any], ...]
    total_count: int | None
    page_no: int | None
    num_of_rows: int | None


@dataclass(frozen=True)
class MedicalDeviceModelRecord:
    product_serial_number: str | None
    regional_office: str | None
    industry_name: str | None
    permission_type: str | None
    permit_number: str | None
    product_name: str | None
    permit_date: date | None
    cancellation_status: str | None
    cancellation_date: date | None
    trade_name: str | None
    model_name: str | None
    export_only: bool | None

    @property
    def active_for_domestic_candidate(self) -> bool:
        return not self.cancellation_status and self.export_only is not True


@dataclass(frozen=True)
class MedicalDeviceBusinessRecord:
    company_name: str | None
    industry_type: str | None
    business_status: str | None
    permit_date: date | None
    address: str | None
    business_permit_number: str | None

    @property
    def is_active(self) -> bool:
        return (self.business_status or "").strip() not in {"폐업", "휴업", "취소"}


@dataclass(frozen=True)
class MedicalDeviceIdentityResolution:
    """Fail-closed exact-model resolution within an already verified MFDS product query.

    The model-info API does not expose a server-side model filter. Therefore this resolution is
    intentionally scoped to records returned by an official `PRDLST_NM` lookup and only accepts
    the repository's existing exact normalized model equality. It never promotes substring or
    semantic similarity to official identity.
    """

    query_model: str
    exact_matches: tuple[MedicalDeviceModelRecord, ...]

    @property
    def confirmed(self) -> bool:
        return bool(self.exact_matches)

    @property
    def ambiguous(self) -> bool:
        permit_numbers = {
            (item.permit_number or "").strip()
            for item in self.exact_matches
            if (item.permit_number or "").strip()
        }
        return len(permit_numbers) > 1


def resolve_exact_model_identity(
    records: Sequence[MedicalDeviceModelRecord],
    model_name: str,
) -> MedicalDeviceIdentityResolution:
    """Resolve only exact model identities from an official product-name result set."""

    query_model = model_name.strip()
    if not query_model:
        return MedicalDeviceIdentityResolution(query_model="", exact_matches=())

    matches = tuple(
        item for item in records if exact_model_match(query_model, item.model_name)
    )
    return MedicalDeviceIdentityResolution(query_model=query_model, exact_matches=matches)


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _date_or_none(value: Any) -> date | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _text_or_none(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _bool_yes_no(value: Any) -> bool | None:
    text = (_text_or_none(value) or "").casefold()
    if text in {"예", "yes", "y", "true", "1"}:
        return True
    if text in {"아니오", "no", "n", "false", "0"}:
        return False
    return None


def _raise_for_header(container: Mapping[str, Any]) -> None:
    header = container.get("header")
    if not isinstance(header, Mapping):
        return
    result_code = str(header.get("resultCode") or "").strip()
    result_msg = str(header.get("resultMsg") or "").strip()
    if result_code and result_code not in SUCCESS_RESULT_CODES:
        raise PublicDataClientError(
            f"MFDS API error resultCode={result_code} resultMsg={result_msg or '-'}"
        )


def unwrap_mfds_page(payload: Mapping[str, Any]) -> MfdsPage:
    """Normalize the common data.go.kr response/body/items envelope used by MFDS APIs."""

    response = payload.get("response", payload)
    if not isinstance(response, Mapping):
        raise PublicDataClientError("MFDS response must be an object")

    _raise_for_header(response)
    body = response.get("body", {})
    if not isinstance(body, Mapping):
        raise PublicDataClientError("MFDS response body must be an object")

    raw_items = body.get("items", [])
    if isinstance(raw_items, Mapping) and "item" in raw_items:
        raw_items = raw_items["item"]
    if raw_items is None:
        raw_items = []
    if isinstance(raw_items, Mapping):
        raw_items = [raw_items]
    if not isinstance(raw_items, list):
        raise PublicDataClientError("MFDS response items must be a list or item object")

    items = tuple(dict(item) for item in raw_items if isinstance(item, Mapping))
    return MfdsPage(
        items=items,
        total_count=_int_or_none(body.get("totalCount")),
        page_no=_int_or_none(body.get("pageNo")),
        num_of_rows=_int_or_none(body.get("numOfRows")),
    )


def parse_model_record(record: Mapping[str, Any]) -> MedicalDeviceModelRecord:
    return MedicalDeviceModelRecord(
        product_serial_number=_text_or_none(record.get("MDEQ_PRDLST_SN")),
        regional_office=_text_or_none(record.get("INST_AREA_DIVS_NM")),
        industry_name=_text_or_none(record.get("INDT_NM")),
        permission_type=_text_or_none(record.get("PRMSN_DCLR_DIVS_NM")),
        permit_number=_text_or_none(record.get("MEDDEV_ITEM_NO")),
        product_name=_text_or_none(record.get("PRDLST_NM")),
        permit_date=_date_or_none(record.get("PRMSN_YMD")),
        cancellation_status=_text_or_none(record.get("RTRCN_DSCTN_DIVS_CD")),
        cancellation_date=_date_or_none(record.get("DSCTN_RTRCN_YMD")),
        trade_name=_text_or_none(record.get("PRDT_NM_INFO")),
        model_name=_text_or_none(record.get("TYPE_INFO")),
        export_only=_bool_yes_no(record.get("EXPORT_YN")),
    )


def parse_business_record(record: Mapping[str, Any]) -> MedicalDeviceBusinessRecord:
    address_parts = [
        text
        for text in (
            _text_or_none(record.get("ADRES1")),
            _text_or_none(record.get("ADRES2")),
        )
        if text
    ]
    return MedicalDeviceBusinessRecord(
        company_name=_text_or_none(record.get("ENTRPS")),
        industry_type=_text_or_none(record.get("INDUTY_TYPE")),
        business_status=_text_or_none(record.get("BIZ_STTUS")),
        permit_date=_date_or_none(record.get("PRMISN_DT")),
        address=" ".join(address_parts) or None,
        business_permit_number=_text_or_none(record.get("MEDDEV_ENTP_NO")),
    )


class MfdsModelInfoClient:
    """Official MFDS model-info adapter.

    The official operation supports `PRDLST_NM` as a request filter. This is intentionally used
    only after a product class/name is known. It does not infer clinical substitutability.
    """

    def __init__(
        self,
        service_key: str,
        *,
        base_url: str = MFDS_MODEL_INFO_BASE_URL,
        client: PublicDataPortalClient | None = None,
        timeout_seconds: float = 20.0,
        max_retries: int = 3,
    ) -> None:
        self.base_url = base_url
        self.client = client or PublicDataPortalClient(
            service_key,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )

    def fetch_page(
        self,
        *,
        product_name: str,
        page_no: int = 1,
        num_of_rows: int = 100,
    ) -> MfdsPage:
        product_name = product_name.strip()
        if not product_name:
            raise ValueError("product_name is required for MFDS model search")
        payload = self.client.get_json(
            self.base_url,
            MFDS_MODEL_INFO_OPERATION,
            PRDLST_NM=product_name,
            pageNo=page_no,
            numOfRows=num_of_rows,
        )
        return unwrap_mfds_page(payload)

    def search_models(
        self,
        product_name: str,
        *,
        max_pages: int = 10,
        num_of_rows: int = 100,
    ) -> tuple[MedicalDeviceModelRecord, ...]:
        records: list[MedicalDeviceModelRecord] = []
        for page_no in range(1, max_pages + 1):
            page = self.fetch_page(
                product_name=product_name,
                page_no=page_no,
                num_of_rows=num_of_rows,
            )
            records.extend(parse_model_record(item) for item in page.items)
            if not page.items:
                break
            if page.total_count is not None and len(records) >= page.total_count:
                break
            if len(page.items) < num_of_rows:
                break
        return tuple(records)


class MfdsBusinessLicenseClient:
    """Official MFDS medical-device business permit lookup."""

    def __init__(
        self,
        service_key: str,
        *,
        base_url: str = MFDS_BUSINESS_LICENSE_BASE_URL,
        client: PublicDataPortalClient | None = None,
        timeout_seconds: float = 20.0,
        max_retries: int = 3,
    ) -> None:
        self.base_url = base_url
        self.client = client or PublicDataPortalClient(
            service_key,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )

    def search_company(
        self,
        company_name: str,
        *,
        page_no: int = 1,
        num_of_rows: int = 100,
    ) -> tuple[MedicalDeviceBusinessRecord, ...]:
        company_name = company_name.strip()
        if not company_name:
            raise ValueError("company_name is required for MFDS business lookup")
        payload = self.client.get_json(
            self.base_url,
            MFDS_BUSINESS_LICENSE_OPERATION,
            Entrps=company_name,
            pageNo=page_no,
            numOfRows=num_of_rows,
        )
        page = unwrap_mfds_page(payload)
        return tuple(parse_business_record(item) for item in page.items)
