from pathlib import Path

import pytest

from purchase_price.services.quote_upload_security import temporary_quote_upload


class FakeUpload:
    name = "quote.pdf"

    def getvalue(self) -> bytes:
        return b"private quote bytes"


def test_temporary_quote_upload_is_deleted_after_success() -> None:
    observed: Path | None = None
    with temporary_quote_upload(FakeUpload()) as path:
        observed = path
        assert path.exists()
        assert path.read_bytes() == b"private quote bytes"

    assert observed is not None
    assert not observed.exists()


def test_temporary_quote_upload_is_deleted_after_failure() -> None:
    observed: Path | None = None

    with pytest.raises(RuntimeError):
        with temporary_quote_upload(FakeUpload()) as path:
            observed = path
            assert path.exists()
            raise RuntimeError("parser failed")

    assert observed is not None
    assert not observed.exists()


def test_temporary_quote_upload_rejects_unapproved_suffix() -> None:
    class BadUpload(FakeUpload):
        name = "quote.txt"

    with pytest.raises(ValueError):
        with temporary_quote_upload(BadUpload()):
            pass
