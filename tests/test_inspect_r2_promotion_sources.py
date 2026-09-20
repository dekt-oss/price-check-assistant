from __future__ import annotations

from types import SimpleNamespace

from purchase_price.scripts.inspect_r2_promotion_sources import (
    build_inspection,
    inspect_payload,
)


def test_inspect_payload_extracts_identity_and_origin_fields() -> None:
    payload = {
        "response": {
            "body": {
                "items": [
                    {
                        "prdctIdntNo": "12345678",
                        "prdctIdntNoNm": (
                            "DNA서열분석기, Oxford nanopore technologies, (GB)MinION MK1D"
                        ),
                        "dtilPrdctClsfcNo": "4111549901",
                        "prdctOrgplceNm": "영국(GB)",
                        "unrelated": "ignore me",
                    }
                ]
            }
        }
    }

    rows = inspect_payload(
        payload,
        model_name="MinION Mk1D",
        product_title="DNA서열분석기, Oxford nanopore technologies, (GB)MinION MK1D",
    )

    assert rows == [
        {
            "prdctIdntNo": "12345678",
            "prdctIdntNoNm": "DNA서열분석기, Oxford nanopore technologies, (GB)MinION MK1D",
            "dtilPrdctClsfcNo": "4111549901",
            "prdctOrgplceNm": "영국(GB)",
        }
    ]


def test_build_inspection_reads_each_raw_source_once() -> None:
    raw_key = "raw/v1/getSpcifyPrdlstPrcureInfoList-page/aa/aa/" + ("a" * 64) + ".json.gz"
    payload = {
        "items": [
            {
                "prdctIdntNoNm": "DNA서열분석기, Oxford nanopore technologies, (GB)MinION MK1D",
                "prdctIdntNo": "12345678",
            }
        ]
    }

    class FakeReader:
        bucket = "test-bucket"

        def __init__(self) -> None:
            self.calls = 0

        def get_public_json(self, obj):
            self.calls += 1
            assert obj.key == raw_key
            return payload

    reader = FakeReader()
    report = {
        "schema": "r2-search-recall-report-v1",
        "cases": [
            {
                "case_id": "minion_mk1d",
                "query": {"model_name": "MinION Mk1D"},
                "promotion_candidates": [
                    {
                        "raw_object_key": raw_key,
                        "product_title": (
                            "DNA서열분석기, Oxford nanopore technologies, (GB)MinION MK1D"
                        ),
                    },
                    {
                        "raw_object_key": raw_key,
                        "product_title": (
                            "DNA서열분석기, Oxford nanopore technologies, (GB)MinION MK1D"
                        ),
                    },
                ],
            }
        ],
    }

    result = build_inspection(report, reader=reader)

    assert reader.calls == 1
    assert result["status"] == "SUCCESS"
    assert result["source_count"] == 1
    assert result["sources"][0]["matching_record_count"] == 1
