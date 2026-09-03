from __future__ import annotations

import csv
from pathlib import Path

from purchase_price.config import get_settings

BENCHMARK_PATH = Path("data/phase0_products.csv")


def main() -> None:
    settings = get_settings()
    with BENCHMARK_PATH.open(encoding="utf-8-sig", newline="") as fp:
        rows = list(csv.DictReader(fp))

    print(f"Phase 0 benchmark rows: {len(rows)}")
    print(f"DATA_GO_KR_SERVICE_KEY configured: {bool(settings.data_go_kr_service_key)}")
    print(f"G2B shopping base URL configured: {bool(settings.g2b_shopping_base_url)}")
    print(f"G2B contract base URL configured: {bool(settings.g2b_contract_base_url)}")

    for index, row in enumerate(rows, start=1):
        identity = " | ".join(
            value
            for value in [row.get("manufacturer"), row.get("product_name"), row.get("model_name")]
            if value
        )
        print(f"{index:02d}. {identity}")


if __name__ == "__main__":
    main()
