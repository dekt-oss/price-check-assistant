from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from purchase_price.clients.data_go_kr import PublicDataClientError, PublicDataPortalClient

# The PPS 2026-07-08 migration notice documents the new service route with http://. The public
# gateway also serves the same route over TLS; runtime defaults to HTTPS so the service key is not
# sent in clear text while preserving the documented host/path contract.
G2B_CATALOG_DOCUMENTED_BASE_URL = "http://apis.data.go.kr/1230000/ao/ThngListInfoService02"
G2B_CATALOG_BASE_URL = "https://apis.data.go.kr/1230000/ao/ThngListInfoService02"
G2B_CATALOG_ATTRIBUTE_OPERATION = "getPrdctIndvAtrbInfoList02"


@dataclass(frozen=True)
class G2BProductAttribute:
    product_id: str
    product_name: str
    detail_product_code: str
    attribute_name: str
    attribute_value: str
    attribute_unit: str = ""


@dataclass(frozen=True)
class G2BCatalogResult:
    product_id: str
    attributes: tuple[G2BProductAttribute, ...]
    request_count: int = 1

    @property
    def detail_product_codes(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                attribute.detail_product_code
                for attribute in self.attributes
                if attribute.detail_product_code
            )
        )


def _items_from_payload(payload: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    response = payload.get("response", payload)
    if not isinstance(response, Mapping):
        raise PublicDataClientError("G2B catalog response must be an object")
    header = response.get("header")
    if isinstance(header, Mapping):
        code = str(header.get("resultCode") or "").strip()
        if code and code not in {"0", "00", "000"}:
            message = str(header.get("resultMsg") or "").strip()
            raise PublicDataClientError(
                f"G2B catalog API error resultCode={code} resultMsg={message or '-'}"
            )
    body = response.get("body", {})
    if not isinstance(body, Mapping):
        raise PublicDataClientError("G2B catalog response body must be an object")
    raw = body.get("items", [])
    if isinstance(raw, Mapping) and "item" in raw:
        raw = raw["item"]
    if raw is None:
        return ()
    if isinstance(raw, Mapping):
        raw = [raw]
    if not isinstance(raw, list):
        raise PublicDataClientError("G2B catalog response items must be a list or item object")
    return tuple(dict(item) for item in raw if isinstance(item, Mapping))


def _parse_attribute(item: Mapping[str, Any], *, requested_product_id: str) -> G2BProductAttribute | None:
    product_id = str(item.get("prdctIdntNo") or "").strip()
    # This resolver is identity-strengthening only. Never accept a row for another item id merely
    # because the upstream response happened to contain it.
    if not product_id or product_id != requested_product_id:
        return None
    return G2BProductAttribute(
        product_id=product_id,
        product_name=str(item.get("prdctIdntNoNm") or "").strip(),
        detail_product_code=str(item.get("dtilPrdctClsfcNo") or "").strip(),
        attribute_name=str(item.get("attrNm") or "").strip(),
        attribute_value=str(item.get("attrVal") or "").strip(),
        attribute_unit=str(item.get("attrUnit") or "").strip(),
    )


class G2BCatalogClient:
    """Resolve official item attributes by exact PPS product-identification number.

    The endpoint is not a fuzzy product-name search. It can strengthen an already observed
    `prdctIdntNo`, but it must never promote a Research alias or specification-similar candidate to
    official identity on text similarity alone.
    """

    def __init__(
        self,
        service_key: str,
        *,
        base_url: str = G2B_CATALOG_BASE_URL,
        timeout_seconds: float = 20.0,
        max_retries: int = 3,
        client: PublicDataPortalClient | None = None,
    ) -> None:
        self.base_url = base_url
        self.client = client or PublicDataPortalClient(
            service_key,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )

    def fetch_attributes(
        self,
        *,
        product_id: str,
        page_no: int = 1,
        num_of_rows: int = 100,
    ) -> G2BCatalogResult:
        product_id = product_id.strip()
        if not product_id:
            raise ValueError("product_id is required")
        if page_no < 1 or num_of_rows < 1:
            raise ValueError("page_no and num_of_rows must be positive")

        payload = self.client.get_json(
            self.base_url,
            G2B_CATALOG_ATTRIBUTE_OPERATION,
            pageNo=page_no,
            numOfRows=num_of_rows,
            prdctIdntNo=product_id,
        )
        attributes = tuple(
            parsed
            for item in _items_from_payload(payload)
            if (parsed := _parse_attribute(item, requested_product_id=product_id)) is not None
        )
        return G2BCatalogResult(product_id=product_id, attributes=attributes)
