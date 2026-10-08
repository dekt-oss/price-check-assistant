"""Fill 종별 · 소재지 · 병상수 in ``data/hospital_master.json`` from HIRA (data.go.kr).

    python -m purchase_price.scripts.sync_hira_hospital_info            # all 8 hospitals
    python -m purchase_price.scripts.sync_hira_hospital_info --dry-run  # print only

Needs ``DATA_GO_KR_SERVICE_KEY`` with 활용신청 for 건강보험심사평가원_병원정보서비스 (15001698) and
_의료기관별상세정보서비스 (15001699). Without it the script stops and changes nothing.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from purchase_price.clients.data_go_kr import PublicDataClientError, PublicDataPortalClient
from purchase_price.services import hira_hospital_info as hira
from purchase_price.services import hospital_master as master_service


def _service_key() -> str:
    key = os.environ.get("DATA_GO_KR_SERVICE_KEY", "").strip()
    if key:
        return key
    try:
        from purchase_price.config import get_settings

        return (get_settings().data_go_kr_service_key or "").strip()
    except Exception:  # pragma: no cover - settings import is best effort
        return ""


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--master", type=Path, default=master_service.DEFAULT_MASTER_FILE)
    parser.add_argument("--hospital", action="append", default=[], help="병원 ID (여러 번 가능)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    key = _service_key()
    if not key:
        print("DATA_GO_KR_SERVICE_KEY가 없어 심평원 자료를 가져올 수 없습니다. 아무것도 바꾸지 않았습니다.")
        return 2
    payload = json.loads(args.master.read_text(encoding="utf-8"))
    master = master_service.load_hospital_master(args.master)
    with PublicDataPortalClient(key) as client:
        try:
            payload, results = hira.sync_master(
                client, master, payload, as_of=date.today(), hospital_ids=args.hospital
            )
        except PublicDataClientError as exc:
            print(f"심평원 서비스 호출 실패(활용신청 안 됨 가능성): {exc}")
            print("data.go.kr에서 병원정보서비스·의료기관별상세정보서비스 활용신청 후 다시 실행하세요.")
            print("hospital_master.json은 바꾸지 않았습니다.")
            return 3
    for result in results:
        detail = (
            f"{result.hira.name} {result.hira.type_name} 병상 {result.bed_count if result.bed_count is not None else '자료 없음'}"
            if result.hira
            else result.note
        )
        print(f"{result.hospital_id}: {result.status} {detail}")
    if args.dry_run:
        print("dry-run: 파일을 쓰지 않았습니다.")
        return 0
    hira.write_master(payload, args.master)
    print(f"updated {args.master}")
    return 0 if all(r.status == "matched" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
