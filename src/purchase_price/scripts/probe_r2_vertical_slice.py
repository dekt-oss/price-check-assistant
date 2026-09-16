from __future__ import annotations

import argparse
import json

from purchase_price.clients.data_go_kr import PublicDataPortalClient
from purchase_price.config import get_settings
from purchase_price.services.g2b_catalog import (
    G2B_CATALOG_ATTRIBUTE_OPERATION,
    G2B_CATALOG_BASE_URL,
)
from purchase_price.storage.r2 import R2RawEvidenceStore

DEFAULT_PRODUCT_ID = "24888744"


def run_vertical_slice(*, product_id: str) -> dict[str, object]:
    settings = get_settings()
    service_key = (settings.resolved_g2b_catalog_service_key or "").strip()
    if not service_key:
        raise RuntimeError("G2B catalog service key is not configured")

    base_url = settings.g2b_catalog_base_url or G2B_CATALOG_BASE_URL
    with PublicDataPortalClient(
        service_key,
        timeout_seconds=settings.g2b_request_timeout_seconds,
        max_retries=settings.g2b_max_retries,
    ) as portal:
        payload = portal.get_json(
            base_url,
            G2B_CATALOG_ATTRIBUTE_OPERATION,
            pageNo=1,
            numOfRows=100,
            prdctIdntNo=product_id,
        )

    store = R2RawEvidenceStore.from_settings(settings)
    first = store.put_public_json(
        source_operation=G2B_CATALOG_ATTRIBUTE_OPERATION,
        payload=payload,
    )
    roundtrip = store.get_public_json(first)
    if roundtrip != payload:
        raise RuntimeError("R2 vertical slice roundtrip payload mismatch")

    second = store.put_public_json(
        source_operation=G2B_CATALOG_ATTRIBUTE_OPERATION,
        payload=payload,
    )
    if second.key != first.key or second.payload_hash != first.payload_hash:
        raise RuntimeError("R2 vertical slice content address changed for identical payload")
    if second.created:
        raise RuntimeError("R2 vertical slice duplicate payload unexpectedly created a new object")

    return {
        "status": "SUCCESS",
        "source": "G2B_CATALOG",
        "operation": G2B_CATALOG_ATTRIBUTE_OPERATION,
        "product_id": product_id,
        "r2_key": first.key,
        "payload_hash": first.payload_hash,
        "first_created": first.created,
        "duplicate_created": second.created,
        "roundtrip_equal": True,
        "uncompressed_bytes": first.uncompressed_bytes,
        "stored_bytes": first.stored_bytes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one live G2B -> R2 vertical slice")
    parser.add_argument("--product-id", default=DEFAULT_PRODUCT_ID)
    args = parser.parse_args()
    report = run_vertical_slice(product_id=args.product_id)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
