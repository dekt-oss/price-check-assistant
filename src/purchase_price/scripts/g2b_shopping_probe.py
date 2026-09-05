from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from purchase_price.clients.data_go_kr import PublicDataPortalClient
from purchase_price.collectors.g2b_shopping import (
    G2B_SHOPPING_BASE_URL,
    G2BShoppingOperation,
    unwrap_g2b_page,
)
from purchase_price.config import get_settings


def _parse_param(raw: str) -> tuple[str, str]:
    if "=" not in raw:
        raise argparse.ArgumentTypeError("--param must be KEY=VALUE")
    key, value = raw.split("=", 1)
    if not key.strip():
        raise argparse.ArgumentTypeError("--param key must not be empty")
    return key.strip(), value


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Probe one verified G2B Shopping operation without committing service keys."
    )
    parser.add_argument(
        "operation",
        choices=[operation.value for operation in G2BShoppingOperation],
    )
    parser.add_argument(
        "--param",
        action="append",
        default=[],
        type=_parse_param,
        help="Operation parameter in KEY=VALUE form. Repeat as needed.",
    )
    parser.add_argument(
        "--save",
        type=Path,
        help="Optional local JSON output path. Use .local/ so it stays out of Git.",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    settings = get_settings()
    service_key = settings.resolved_g2b_service_key
    if not service_key:
        raise SystemExit(
            "G2B_SERVICE_KEY or legacy DATA_GO_KR_SERVICE_KEY is not configured. "
            "Add it only to an approved secret store for live API calls."
        )

    params: dict[str, Any] = dict(args.param)
    client = PublicDataPortalClient(
        service_key,
        timeout_seconds=settings.g2b_request_timeout_seconds,
        max_retries=settings.g2b_max_retries,
    )
    base_url = settings.g2b_shopping_base_url or G2B_SHOPPING_BASE_URL
    payload = client.get_json(base_url, args.operation, **params)
    page = unwrap_g2b_page(payload)

    print(f"operation={args.operation}")
    print(f"items={len(page.items)} total_count={page.total_count}")
    if page.items:
        print("first_item_fields=")
        for key in sorted(page.items[0]):
            print(f"  - {key}")

    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"saved={args.save}")


if __name__ == "__main__":
    main()
