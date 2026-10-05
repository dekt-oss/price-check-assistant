from __future__ import annotations

import threading
from typing import Any

from purchase_price.services.mfds_device_intelligence import (
    MODEL_INFO_PAGE_SIZE,
    MfdsModelInfoClient,
)


def _row(index: int, item: str = "수허 00-001 호") -> dict[str, Any]:
    return {
        "MDEQ_PRDLST_SN": str(index),
        "INDT_NM": "수입업",
        "PRMSN_DCLR_DIVS_NM": "허가",
        "MEDDEV_ITEM_NO": item,
        "PRDLST_NM": "심장충격기",
        "PRMSN_YMD": "2020-01-01",
        "TYPE_INFO": f"MODEL-{index}",
        "EXPORT_YN": "아니오",
    }


class FakeClient:
    def __init__(self, total: int) -> None:
        self.total = total
        self.calls: list[dict[str, Any]] = []
        self.threads: set[str] = set()
        self.lock = threading.Lock()

    def get_json(self, base_url: str, endpoint: str, **params: Any) -> dict[str, Any]:
        with self.lock:
            self.calls.append(params)
            self.threads.add(threading.current_thread().name)
        if "MEDDEV_ITEM_NO" in params:
            items = [_row(1, params["MEDDEV_ITEM_NO"]), _row(2, "수허 99-999 호")]
            total = len(items)
        else:
            size = params["numOfRows"]
            start = (params["pageNo"] - 1) * size
            items = [_row(i) for i in range(start, min(start + size, self.total))]
            total = self.total
        return {
            "header": {"resultCode": "00"},
            "body": {"items": items, "totalCount": total, "pageNo": params["pageNo"]},
        }


def test_search_models_uses_large_pages_and_fetches_remaining_pages_in_parallel() -> None:
    fake = FakeClient(total=1_632)
    client = MfdsModelInfoClient("key", client=fake)

    records = client.search_models("심장충격기")

    assert len(records) == 1_632
    assert [record.model_name for record in records[:2]] == ["MODEL-0", "MODEL-1"]
    assert records[-1].model_name == "MODEL-1631"
    assert {call["numOfRows"] for call in fake.calls} == {MODEL_INFO_PAGE_SIZE}
    assert sorted(call["pageNo"] for call in fake.calls) == [1, 2, 3, 4]
    assert len(fake.threads) > 1


def test_search_models_respects_max_pages() -> None:
    fake = FakeClient(total=5_000)

    records = MfdsModelInfoClient("key", client=fake).search_models("x", max_pages=2)

    assert len(records) == 1_000
    assert sorted(call["pageNo"] for call in fake.calls) == [1, 2]


def test_search_models_single_page_makes_one_request() -> None:
    fake = FakeClient(total=120)

    records = MfdsModelInfoClient("key", client=fake).search_models("x")

    assert len(records) == 120
    assert len(fake.calls) == 1


def test_search_item_numbers_is_exact_and_one_request_per_item() -> None:
    fake = FakeClient(total=0)

    records = MfdsModelInfoClient("key", client=fake).search_item_numbers(
        ["수허 98-868 호", "수허 98-868 호", "제인 16-4842 호"]
    )

    assert sorted(call["MEDDEV_ITEM_NO"] for call in fake.calls) == ["수허 98-868 호", "제인 16-4842 호"]
    assert {record.permit_number for record in records} == {"수허 98-868 호", "제인 16-4842 호"}
    assert MfdsModelInfoClient("key", client=fake).search_item_numbers([]) == ()
