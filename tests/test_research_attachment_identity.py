from __future__ import annotations

import io
import zipfile

import httpx
import openpyxl

from purchase_price.schemas import ProductQuery
from purchase_price.services.g2b_market_models import ResearchAttachment
from purchase_price.services.research_attachment_identity import (
    AttachmentIdentityStatus,
    classify_attachment_identity,
    extract_attachment_text,
    inspect_attachment,
)


def test_attachment_text_can_confirm_maquet_flow_c_exact_identity() -> None:
    query = ProductQuery(product_name="마취기", manufacturer="Maquet", model_name="FLOW-C")

    status, model_found, manufacturer_found, excerpt = classify_attachment_identity(
        "제조사 MAQUET / 모델 FLOW C / Anesthesia Workstation", query
    )

    assert status == AttachmentIdentityStatus.EXACT_IDENTITY
    assert model_found
    assert manufacturer_found
    assert "MAQUET" in excerpt


def test_model_without_requested_manufacturer_is_not_exact_identity() -> None:
    query = ProductQuery(product_name="마취기", manufacturer="Maquet", model_name="FLOW-C")

    status, model_found, manufacturer_found, _ = classify_attachment_identity(
        "Model FLOW-C / manufacturer unknown", query
    )

    assert status == AttachmentIdentityStatus.MODEL_MATCH
    assert model_found
    assert not manufacturer_found


def test_manufacturer_alias_is_detected_but_does_not_replace_model_requirement() -> None:
    query = ProductQuery(product_name="마취기", manufacturer="Draeger", model_name="Atlan")

    status, model_found, manufacturer_found, _ = classify_attachment_identity(
        "제조사: Dräger / 마취 워크스테이션", query
    )

    assert status == AttachmentIdentityStatus.MANUFACTURER_MATCH
    assert not model_found
    assert manufacturer_found


def test_hwpx_section_text_is_extractable() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "Contents/section0.xml",
            "<root xmlns:h='urn:test'><h:p>MAQUET FLOW-C 마취기 규격</h:p></root>",
        )

    text = extract_attachment_text(
        name="규격서.hwpx", url="https://files.example.test/spec.hwpx", data=buffer.getvalue()
    )

    assert "MAQUET FLOW-C" in text


def test_xlsx_text_is_extractable() -> None:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet["A1"] = "Manufacturer"
    sheet["B1"] = "Maquet"
    sheet["A2"] = "Model"
    sheet["B2"] = "FLOW-C"
    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    text = extract_attachment_text(
        name="규격.xlsx", url="https://files.example.test/spec.xlsx", data=buffer.getvalue()
    )

    assert "Maquet" in text
    assert "FLOW-C" in text


def test_binary_hwp_is_explicitly_unsupported() -> None:
    query = ProductQuery(product_name="마취기", manufacturer="Maquet", model_name="FLOW-C")
    attachment = ResearchAttachment("규격서.hwp", "https://files.example.test/spec.hwp")
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"not-hwp"))

    with httpx.Client(transport=transport) as client:
        result = inspect_attachment(attachment, query, client=client)

    assert result.status == AttachmentIdentityStatus.UNSUPPORTED
    assert result.error_type == "UnsupportedAttachmentError"


def test_download_failure_is_not_reported_as_no_match() -> None:
    query = ProductQuery(product_name="마취기", manufacturer="Maquet", model_name="FLOW-C")
    attachment = ResearchAttachment("규격.txt", "https://files.example.test/spec.txt")
    transport = httpx.MockTransport(lambda request: httpx.Response(503, text="unavailable"))

    with httpx.Client(transport=transport) as client:
        result = inspect_attachment(attachment, query, client=client)

    assert result.status == AttachmentIdentityStatus.DOWNLOAD_FAILED
    assert result.status != AttachmentIdentityStatus.NO_MATCH
