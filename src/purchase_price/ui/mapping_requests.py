from __future__ import annotations

import csv
from pathlib import Path

DEFAULT_MAPPING_REQUESTS_PATH = Path(__file__).resolve().parents[3] / "data" / "mapping_requests.csv"
_FIELDNAMES = ("product_name", "manufacturer", "model_name")


def _key(product_name: str, manufacturer: str, model_name: str) -> tuple[str, str, str]:
    return tuple(value.strip().casefold() for value in (product_name, manufacturer, model_name))


def register_mapping_request(
    *,
    product_name: str,
    manufacturer: str,
    model_name: str,
    path: Path = DEFAULT_MAPPING_REQUESTS_PATH,
) -> bool:
    """Append one identity-only mapping request; return False when already registered.

    The request registry intentionally excludes quote price, quantity, commercial conditions,
    source document text, and uploaded file metadata.
    """
    values = {
        "product_name": product_name.strip(),
        "manufacturer": manufacturer.strip(),
        "model_name": model_name.strip(),
    }
    if not values["product_name"] and not values["model_name"]:
        raise ValueError("mapping request requires product_name or model_name")

    requested_key = _key(**values)
    existing: set[tuple[str, str, str]] = set()
    if path.exists():
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames and set(_FIELDNAMES).issubset(reader.fieldnames):
                existing = {
                    _key(
                        str(row.get("product_name") or ""),
                        str(row.get("manufacturer") or ""),
                        str(row.get("model_name") or ""),
                    )
                    for row in reader
                }
    if requested_key in existing:
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_FIELDNAMES)
        if write_header:
            writer.writeheader()
        writer.writerow(values)
    return True
