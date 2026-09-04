from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from purchase_price.clients.data_go_kr import PublicDataPortalClient
from purchase_price.collectors.g2b_shopping import G2BShoppingPage, unwrap_g2b_page

G2B_CONTRACT_BASE_URL = "https://apis.data.go.kr/1230000/ao/CntrctInfoService"
G2B_CONTRACT_PRODUCT_SEARCH_OPERATION = "getCntrctInfoListThngPPSSrch"
G2B_CONTRACT_DATASET_URL = "https://www.data.go.kr/data/15129427/openapi.do"


@dataclass(frozen=True)
class G2BContractEvidence:
    decision_contract_number: str | None
    contract_method_name: str | None
    contract_institution_name: str | None
    product_name: str | None
    contract_date: date | None
    detail_url: str | None

    @property
    def dedupe_key(self) -> tuple[str, str, str, str]:
        return (
            self.decision_contract_number or "",
            self.detail_url or "",
            self.product_name or "",
            self.contract_date.isoformat() if self.contract_date else "",
        )


_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "decision_contract_number": ("dcsnCntrctNo", "확정계약번호"),
    "contract_method_name": ("cntrctCnclsMthdNm", "계약체결방법명"),
    "contract_institution_name": ("cntrctInsttNm", "계약기관명"),
    "product_name": ("prdctClsfcNoNm", "품명"),
    "contract_date": ("cntrctCnclsDate", "계약체결일자"),
    "detail_url": ("cntrctDtlInfoUrl", "계약상세정보URL"),
}


def _first_value(record: Mapping[str, Any], logical_name: str) -> Any:
    for key in _FIELD_ALIASES[logical_name]:
        value = record.get(key)
        if value not in (None, ""):
            return value
    return None


def _text_or_none(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _date_or_none(value: Any) -> date | None:
    text = _text_or_none(value)
    if not text:
        return None
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_contract_evidence(record: Mapping[str, Any]) -> G2BContractEvidence:
    return G2BContractEvidence(
        decision_contract_number=_text_or_none(_first_value(record, "decision_contract_number")),
        contract_method_name=_text_or_none(_first_value(record, "contract_method_name")),
        contract_institution_name=_text_or_none(
            _first_value(record, "contract_institution_name")
        ),
        product_name=_text_or_none(_first_value(record, "product_name")),
        contract_date=_date_or_none(_first_value(record, "contract_date")),
        detail_url=_text_or_none(_first_value(record, "detail_url")),
    )


class G2BContractEvidenceClient:
    """Lookup public G2B contract evidence without converting contract totals into unit prices.

    The current official service exposes `getCntrctInfoListThngPPSSrch` for product contract
    searches. This adapter uses the established contract-date inquiry form and intentionally
    returns descriptive contract evidence only. It does not emit `CollectedPrice` and therefore
    cannot enter the reference-price range.
    """

    def __init__(
        self,
        service_key: str,
        *,
        base_url: str = G2B_CONTRACT_BASE_URL,
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

    def fetch_product_contract_page(
        self,
        *,
        product_name: str,
        begin_date: date,
        end_date: date,
        contract_method_code: str = "",
        page_no: int = 1,
        num_of_rows: int = 100,
    ) -> G2BShoppingPage:
        product_name = product_name.strip()
        if not product_name:
            raise ValueError("product_name is required")
        if begin_date > end_date:
            raise ValueError("begin_date must not be after end_date")
        if page_no < 1 or num_of_rows < 1:
            raise ValueError("page_no and num_of_rows must be positive")

        params: dict[str, Any] = {
            "inqryDiv": "1",
            "inqryBgnDate": begin_date.strftime("%Y%m%d"),
            "inqryEndDate": end_date.strftime("%Y%m%d"),
            "pageNo": page_no,
            "numOfRows": num_of_rows,
            "prdctClsfcNoNm": product_name,
        }
        method = contract_method_code.strip()
        if method:
            params["cntrctMthdCd"] = method

        payload = self.client.get_json(
            self.base_url,
            G2B_CONTRACT_PRODUCT_SEARCH_OPERATION,
            **params,
        )
        return unwrap_g2b_page(payload)

    def search_product_contracts(
        self,
        *,
        product_name: str,
        begin_date: date,
        end_date: date,
        contract_method_code: str = "",
        max_pages: int = 10,
        num_of_rows: int = 100,
    ) -> tuple[G2BContractEvidence, ...]:
        if max_pages < 1:
            raise ValueError("max_pages must be positive")

        results: list[G2BContractEvidence] = []
        seen: set[tuple[str, str, str, str]] = set()
        fetched_raw_count = 0

        for page_no in range(1, max_pages + 1):
            page = self.fetch_product_contract_page(
                product_name=product_name,
                begin_date=begin_date,
                end_date=end_date,
                contract_method_code=contract_method_code,
                page_no=page_no,
                num_of_rows=num_of_rows,
            )
            if not page.items:
                break

            fetched_raw_count += len(page.items)
            for raw in page.items:
                evidence = parse_contract_evidence(raw)
                if evidence.dedupe_key in seen:
                    continue
                seen.add(evidence.dedupe_key)
                results.append(evidence)

            if page.total_count is not None and fetched_raw_count >= page.total_count:
                break
            if len(page.items) < num_of_rows:
                break

        return tuple(results)
