import pytest

from purchase_price.clients.data_go_kr import PublicDataPortalClient


def test_service_key_is_required():
    with pytest.raises(ValueError, match="DATA_GO_KR_SERVICE_KEY"):
        PublicDataPortalClient("")


def test_base_url_is_required():
    client = PublicDataPortalClient("fake-key")
    with pytest.raises(ValueError, match="base URL"):
        client.get_json("", "endpoint")
