from __future__ import annotations

import argparse
import json

from purchase_price.config import get_settings
from purchase_price.storage.r2 import R2RawEvidenceStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe Cloudflare R2 storage permissions")
    parser.add_argument(
        "--write-smoke",
        action="store_true",
        help="Also verify put/head/delete permissions using a temporary smoke object",
    )
    parser.add_argument(
        "--raw-smoke",
        action="store_true",
        help="Also upload and read back one deterministic public-provenance raw sample",
    )
    args = parser.parse_args()

    settings = get_settings()
    store = R2RawEvidenceStore.from_settings(settings)
    report: dict[str, object] = {
        "configured": settings.r2_configured,
        "endpoint": settings.resolved_r2_endpoint_url,
        "bucket": settings.resolved_r2_bucket_name,
        "read": store.probe_read_access(),
    }
    if args.write_smoke:
        report["write"] = store.probe_write_access()
    if args.raw_smoke:
        payload = {
            "probe": "price-check-assistant-r2-raw-v1",
            "data_classification": "public-provenance",
            "schema": 1,
        }
        ref = store.put_public_json(source_operation="r2LiveSmoke", payload=payload)
        roundtrip = store.get_public_json(ref)
        if roundtrip != payload:
            raise RuntimeError("R2 raw roundtrip payload mismatch")
        report["raw"] = {
            "status": "SUCCESS",
            "created": ref.created,
            "key": ref.key,
            "payload_hash": ref.payload_hash,
            "uncompressed_bytes": ref.uncompressed_bytes,
            "stored_bytes": ref.stored_bytes,
        }

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
