from __future__ import annotations

from scripts import production_browser_smoke as browser_smoke
from scripts import production_quote_uat_smoke as quote_smoke


class FakeLocator:
    def __init__(self, *, text: str = "", count: int = 1) -> None:
        self.text = text
        self._count = count
        self.clicked = False
        self.waited = False

    @property
    def first(self):
        return self

    def inner_text(self, *, timeout: int):
        del timeout
        return self.text

    def count(self) -> int:
        return self._count

    def click(self, *, timeout: int) -> None:
        del timeout
        self.clicked = True

    def wait_for(self, *, state: str, timeout: int) -> None:
        assert state == "attached"
        assert timeout > 0
        self.waited = True


class FakePage:
    def __init__(self, body_text: str, *, wake_count: int = 1) -> None:
        self.body = FakeLocator(text=body_text)
        self.wake = FakeLocator(count=wake_count)
        self.iframe = FakeLocator()

    def locator(self, selector: str):
        if selector == "body":
            return self.body
        if selector == browser_smoke.APP_IFRAME:
            return self.iframe
        raise AssertionError(f"unexpected selector: {selector}")

    def get_by_text(self, text: str, *, exact: bool):
        assert exact is True
        assert text == browser_smoke.STREAMLIT_WAKE_TEXT
        return self.wake


def _assert_wake_helper(helper) -> None:
    sleeping = FakePage(
        "Zzzz\n"
        + browser_smoke.STREAMLIT_SLEEP_MARKER
        + "\n"
        + browser_smoke.STREAMLIT_WAKE_TEXT
    )
    assert helper(sleeping) is True
    assert sleeping.wake.clicked is True
    assert sleeping.iframe.waited is True

    awake = FakePage("normal Streamlit shell")
    assert helper(awake) is False
    assert awake.wake.clicked is False
    assert awake.iframe.waited is False


def test_browser_smoke_wakes_streamlit_cloud_sleep_screen() -> None:
    _assert_wake_helper(browser_smoke._wake_streamlit_cloud_if_sleeping)


def test_quote_uat_smoke_wakes_streamlit_cloud_sleep_screen() -> None:
    _assert_wake_helper(quote_smoke._wake_streamlit_cloud_if_sleeping)


def test_sleep_screen_without_wake_control_fails_closed() -> None:
    page = FakePage(browser_smoke.STREAMLIT_SLEEP_MARKER, wake_count=0)

    try:
        browser_smoke._wake_streamlit_cloud_if_sleeping(page)
    except RuntimeError as exc:
        assert "without its wake control" in str(exc)
    else:
        raise AssertionError("sleep screen without wake control must fail closed")
