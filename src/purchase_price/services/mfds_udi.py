from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from purchase_price.clients.data_go_kr import PublicDataPortalClient
from purchase_price.services.mfds_device_intelligence import unwrap_mfds_page

MFDS_UDI_CODE_BASE_URL = "https://apis.data.go.kr/1471000/MdeqStdCdInfoService"
MFDS_UDI_CODE_OPERATION = "getMdeqStdCdInq"
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
