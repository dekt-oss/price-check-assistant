from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from purchase_price.clients.data_go_kr import PublicDataClientError, PublicDataPortalClient
from purchase_price.services.mfds_api_keys import is_key_not_registered
from purchase_price.services.mfds_device_intelligence import unwrap_mfds_page

MFDS_UDI_CODE_BASE_URL = "https://apis.data.go.kr/1471000/MdeqStdCdInfoService"
MFDS_UDI_CODE_OPERATION = "getMdeqStdCdInq"
# The 표준코드별 제품정보 service (data.go.kr 15073875) also takes an exact UDIDI_CD filter and answers
# with the product name, model, permit number and company, so the page uses it when the UDI-code
# service (data.go.kr 15073874) is not approved for the deployed key.
MFDS_UDI_PRODUCT_INFO_BASE_URL = "https://apis.data.go.kr/1471000/MdeqStdCdPrdtInfoService03"
MFDS_UDI_PRODUCT_INFO_OPERATION = "getMdeqStdCdPrdtInfoInq03"
UDI_CODE_SERVICE_NAME = "의료기기 표준코드(UDI코드)정보"
UDI_CODE_SERVICE_DATASET_ID = "15073874"
UDI_PRODUCT_INFO_SERVICE_NAME = "의료기기 표준코드별 제품정보"
UDI_PRODUCT_INFO_SERVICE_DATASET_ID = "15073875"
MFDS_UDI_REGISTERED_COMPANY_BASE_URL = (
    "https://apis.data.go.kr/1471000/MdeqStdCdMnftrImptrInfoService"
)
MFDS_UDI_REGISTERED_COMPANY_OPERATION = "getMdeqStdCdMnftrImptrInfoInq"


class _JsonClient(Protocol):
    def get_json(self, base_url: str, endpoint: str, **params: Any) -> dict[str, Any]: ...


@dataclass(frozen=True)
class MedicalDeviceUdiCodeRecord:
    udi_di: str | None
    code_structure_code: str | None
    code_system_name: str | None
    company_name: str | None
    company_type: str | None


@dataclass(frozen=True)
class MedicalDeviceUdiRegisteredCompanyRecord:
    udi_di: str | None
    company_name: str | None
    business_permit_number: str | None
    permit_date: str | None
    address: str | None


@dataclass(frozen=True)
class MedicalDeviceUdiProductRecord:
    udi_di: str | None
    product_name: str | None
    model_name: str | None
    permit_number: str | None
    permit_date: str | None
    classification_no: str | None
    grade: str | None
    company_name: str | None


def _text_or_none(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def parse_udi_code_record(record: Mapping[str, Any]) -> MedicalDeviceUdiCodeRecord:
    return MedicalDeviceUdiCodeRecord(
        udi_di=_text_or_none(record.get("UDIDI_CD")),
        code_structure_code=_text_or_none(record.get("CD_STRCT_DIVS_CD")),
        code_system_name=_text_or_none(record.get("CODE_SYSTEM_NAME")),
        company_name=_text_or_none(record.get("BSSH_NM")),
        company_type=_text_or_none(record.get("INDT_DIVS_NM")),
    )


def parse_udi_product_record(record: Mapping[str, Any]) -> MedicalDeviceUdiProductRecord:
    return MedicalDeviceUdiProductRecord(
        udi_di=_text_or_none(record.get("UDIDI_CD")),
        product_name=_text_or_none(record.get("PRDLST_NM")),
        model_name=_text_or_none(record.get("FOML_INFO")),
        permit_number=_text_or_none(record.get("PERMIT_NO")),
        permit_date=_text_or_none(record.get("PRMSN_YMD")),
        classification_no=_text_or_none(record.get("MDEQ_CLSF_NO")),
        grade=_text_or_none(record.get("CLSF_NO_GRAD_CD")),
        company_name=_text_or_none(record.get("MNFT_IPRT_ENTP_NM")),
    )


def parse_udi_registered_company_record(
    record: Mapping[str, Any],
) -> MedicalDeviceUdiRegisteredCompanyRecord:
    return MedicalDeviceUdiRegisteredCompanyRecord(
        udi_di=_text_or_none(record.get("UDIDI_CD")),
        company_name=_text_or_none(record.get("BSSH_NM")),
        business_permit_number=_text_or_none(record.get("MDEQ_BSSH_PRMSN_NO")),
        permit_date=_text_or_none(record.get("PRMSN_YMD")),
        address=_text_or_none(record.get("BSSH_ADDR")),
    )


def _normalize_udi(value: str | None) -> str:
    return "".join(str(value or "").split()).casefold()


class MfdsUdiCodeClient:
    """Official MFDS UDI-code lookup using the documented exact `UDIDI_CD` filter.

    This API is a forward lookup from a known UDI-DI. It must not be used as a model-name to UDI
    reverse-search mechanism because the official request contract does not expose a model filter.
    """

    def __init__(
        self,
        service_key: str,
        *,
        base_url: str = MFDS_UDI_CODE_BASE_URL,
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

    def lookup_udi(
        self,
        udi_di: str,
        *,
        page_no: int = 1,
        num_of_rows: int = 100,
    ) -> tuple[MedicalDeviceUdiCodeRecord, ...]:
        query = udi_di.strip()
        if not query:
            raise ValueError("udi_di is required for MFDS UDI lookup")

        payload = self.client.get_json(
            self.base_url,
            MFDS_UDI_CODE_OPERATION,
            UDIDI_CD=query,
            pageNo=page_no,
            numOfRows=num_of_rows,
        )
        page = unwrap_mfds_page(payload)
        normalized_query = _normalize_udi(query)
        records = tuple(parse_udi_code_record(item) for item in page.items)
        return tuple(item for item in records if _normalize_udi(item.udi_di) == normalized_query)


class MfdsUdiProductInfoClient:
    """Exact UDI-DI lookup on the 표준코드별 제품정보 service (same `UDIDI_CD` filter)."""

    def __init__(
        self,
        service_key: str,
        *,
        base_url: str = MFDS_UDI_PRODUCT_INFO_BASE_URL,
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

    def lookup_udi(
        self,
        udi_di: str,
        *,
        page_no: int = 1,
        num_of_rows: int = 100,
    ) -> tuple[MedicalDeviceUdiProductRecord, ...]:
        query = udi_di.strip()
        if not query:
            raise ValueError("udi_di is required for MFDS UDI product lookup")

        payload = self.client.get_json(
            self.base_url,
            MFDS_UDI_PRODUCT_INFO_OPERATION,
            UDIDI_CD=query,
            pageNo=page_no,
            numOfRows=num_of_rows,
        )
        page = unwrap_mfds_page(payload)
        normalized_query = _normalize_udi(query)
        records = tuple(parse_udi_product_record(item) for item in page.items)
        return tuple(item for item in records if _normalize_udi(item.udi_di) == normalized_query)


class MfdsUdiRegisteredCompanyClient:
    """Official MFDS manufacturer/importer lookup for a known UDI-DI.

    The public request contract exposes only `UDIDI_CD` and `BSSH_NM` as optional filters.
    This client deliberately implements the exact UDI-DI path only. It does not infer a UDI-DI
    from model names or permit numbers.
    """

    def __init__(
        self,
        service_key: str,
        *,
        base_url: str = MFDS_UDI_REGISTERED_COMPANY_BASE_URL,
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

    def lookup_udi(
        self,
        udi_di: str,
        *,
        page_no: int = 1,
        num_of_rows: int = 100,
    ) -> tuple[MedicalDeviceUdiRegisteredCompanyRecord, ...]:
        query = udi_di.strip()
        if not query:
            raise ValueError("udi_di is required for MFDS registered-company lookup")

        payload = self.client.get_json(
            self.base_url,
            MFDS_UDI_REGISTERED_COMPANY_OPERATION,
            UDIDI_CD=query,
            pageNo=page_no,
            numOfRows=num_of_rows,
        )
        page = unwrap_mfds_page(payload)
        normalized_query = _normalize_udi(query)
        records = tuple(parse_udi_registered_company_record(item) for item in page.items)
        return tuple(item for item in records if _normalize_udi(item.udi_di) == normalized_query)


@dataclass(frozen=True)
class UdiLookupOutcome:
    """One UDI-DI lookup over both official services.

    ``state``: ``found`` | ``empty`` (a service answered, nothing matched) | ``not_connected``
    (every service refused the key as not approved) | ``failed`` (any other error).
    ``approved`` names the services that answered, so the screen can say which are connected.
    """

    state: str
    product_records: tuple[MedicalDeviceUdiProductRecord, ...] = ()
    code_records: tuple[MedicalDeviceUdiCodeRecord, ...] = ()
    error: str = ""
    product_service_ok: bool = False
    code_service_ok: bool = False


def lookup_udi_with_fallback(
    udi_di: str,
    *,
    product_client: MfdsUdiProductInfoClient,
    code_client: MfdsUdiCodeClient,
) -> UdiLookupOutcome:
    """Ask the 제품정보 service first (richer answer), then the UDI-code service.

    A service that is not approved for the deployed key is skipped, not treated as "not found".
    Only when neither service answered is the lookup reported as not connected / failed.
    """

    errors: list[PublicDataClientError | ValueError] = []
    product_ok = code_ok = False
    try:
        product = product_client.lookup_udi(udi_di)
        product_ok = True
        if product:
            return UdiLookupOutcome("found", product_records=product, product_service_ok=True)
    except (PublicDataClientError, ValueError) as exc:
        errors.append(exc)
    try:
        code = code_client.lookup_udi(udi_di)
        code_ok = True
        if code:
            return UdiLookupOutcome(
                "found", code_records=code, product_service_ok=product_ok, code_service_ok=True
            )
    except (PublicDataClientError, ValueError) as exc:
        errors.append(exc)
    if product_ok or code_ok:
        return UdiLookupOutcome("empty", product_service_ok=product_ok, code_service_ok=code_ok)
    if errors and all(isinstance(exc, PublicDataClientError) and is_key_not_registered(exc) for exc in errors):
        return UdiLookupOutcome("not_connected", error=str(errors[0]))
    other = next((exc for exc in errors if not is_key_not_registered(exc)), errors[0])
    return UdiLookupOutcome("failed", error=str(other))
