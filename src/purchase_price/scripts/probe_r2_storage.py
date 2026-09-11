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
    args = parser.parse_args()

    settings = get_settings()
    store = R2RawEvidenceStore.from_settings(settings)
    report: dict[str, object] = {
        "configured": settings.r2_configured,
        "endpoint": settings.resolved_r2_endpoint_url,
        "read": store.probe_read_access(),
    }
    if args.write_smoke:
        report["write"] = store.probe_write_access()

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
