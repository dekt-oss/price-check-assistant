from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

from purchase_price.clients.data_go_kr import PublicDataPortalClient
from purchase_price.services.mfds_device_intelligence import unwrap_mfds_page

MFDS_PRODUCT_INFO_BASE_URL = "https://apis.data.go.kr/1471000/MdeqStdCdPrdtInfoService03"
MFDS_PRODUCT_INFO_OPERATION = "getMdeqStdCdPrdtInfoInq03"
_MODEL_FILTER = "FOML_INFO"

_SAFE_FIELDS = (
    "UDIDI_CD",
    "PRDLST_NM",
    "MDEQ_CLSF_NO",
    "CLSF_NO_GRAD_CD",
    "PERMIT_NO",
    "PRMSN_YMD",
    "FOML_INFO",
    "PRDT_NM_INFO",
    "MNFT_IPRT_ENTP_NM",
)


class _JsonClient(Protocol):
    def get_json(self, base_url: str, endpoint: str, **params: Any) -> dict[str, Any]: ...


def _normalize(value: object | None) -> str:
    return "".join(str(value or "").split()).casefold()


def _safe_record(item: Mapping[str, Any]) -> dict[str, str | None]:
    return {
        key: str(item.get(key)).strip() if item.get(key) not in (None, "") else None
        for key in _SAFE_FIELDS
    }


def probe_product_info(
    client: _JsonClient,
    *,
    model_name: str,
    num_of_rows: int = 20,
) -> dict[str, Any]:
    query = model_name.strip()
    if not query:
        raise ValueError("model_name is required")
    payload = client.get_json(
        MFDS_PRODUCT_INFO_BASE_URL,
        MFDS_PRODUCT_INFO_OPERATION,
        FOML_INFO=query,
        pageNo=1,
        numOfRows=num_of_rows,
    )
    page = unwrap_mfds_page(payload)
    records = [_safe_record(item) for item in page.items]
    normalized = _normalize(query)
    exact = [item for item in records if _normalize(item.get("FOML_INFO")) == normalized]
    return {
        "status": "SUCCESS",
        "source": "MFDS medical-device UDI product information",
        "base_url": MFDS_PRODUCT_INFO_BASE_URL,
        "operation": MFDS_PRODUCT_INFO_OPERATION,
        "request_filter": _MODEL_FILTER,
        "query_model": query,
        "total_count": page.total_count,
        "returned_count": len(records),
        "exact_model_count": len(exact),
        "returned_field_names": sorted({key for item in page.items for key in item}),
        "records": records,
        "writes_performed": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only live probe for the MFDS product-info model filter contract."
    )
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--expect-hit", action="store_true")
    args = parser.parse_args()

    service_key = (
        os.getenv("MFDS_SERVICE_KEY")
        or os.getenv("DATA_GO_KR_MARKET_SERVICE_KEY")
        or os.getenv("DATA_GO_KR_SERVICE_KEY")
        or ""
    ).strip()
    if not service_key:
        raise SystemExit("MFDS service key is not configured")

    with PublicDataPortalClient(service_key, timeout_seconds=20.0, max_retries=3) as client:
        report = probe_product_info(client, model_name=args.model_name)

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    if args.expect_hit and not report["exact_model_count"]:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
