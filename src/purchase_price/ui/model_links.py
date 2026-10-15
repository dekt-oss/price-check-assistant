"""New-tab links to another model's price result (UX v1.2 Q2).

Moving to a different model keeps the current result open: the link opens the app's search URL
(``?q=<model>&identity=<token>&exact=1``, the same parameters ``_open_model_from_overview`` sets)
in a new browser tab. Streamlit Cloud runs the app inside an iframe served from ``/~/+/``; a
relative link would open that inner page, so the link is always absolute and never ``/~/+/``.

New module (Streamlit keeps old modules after a deploy; a new module is always imported fresh).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

MODEL_LINKS_V1 = True
PRODUCTION_APP_URL = "https://bp-price-research.streamlit.app/"
PUBLIC_APP_URL_ENV = "PUBLIC_APP_URL"
LINK_COLUMN = "가격 조사"
LINK_TEXT = "새 탭에서 보기"
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_INNER_FRAME_PATH = "/~/+"


def _origin(url: str) -> str:
    """``scheme://host[:port]/`` of ``url``; '' when it is not an http(s) URL."""

    parts = urlsplit(url.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return ""
    return urlunsplit((parts.scheme, parts.netloc, "/", "", ""))


def _clean_base(url: str) -> str:
    """An app base URL ending in '/', without query, fragment or the inner-iframe path."""

    parts = urlsplit(url.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return ""
    path = parts.path or "/"
    cut = path.find(_INNER_FRAME_PATH)
    if cut >= 0:
        path = path[:cut]
    if not path.endswith("/"):
        path += "/"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def _context_url() -> str:
    try:
        import streamlit as st

        return str(getattr(st.context, "url", "") or "")
    except Exception:
        return ""


def app_base_url(*, env: Mapping[str, str] | None = None, context_url: str | None = None) -> str:
    """``PUBLIC_APP_URL`` when set; the local dev origin on localhost; else the Production URL."""

    environ = os.environ if env is None else env
    configured = _clean_base(str(environ.get(PUBLIC_APP_URL_ENV) or ""))
    if configured:
        return configured
    current = _context_url() if context_url is None else context_url
    host = urlsplit(current.strip()).hostname or ""
    if host in LOCAL_HOSTS:
        local = _origin(current)
        if local:
            return local
    return PRODUCTION_APP_URL


def model_search_url(
    model: str,
    *,
    identity_token: str = "",
    exact_company: bool = False,
    base: str | None = None,
) -> str:
    """Absolute search URL for ``model`` (URL-encoded); '' when the model name is empty."""

    name = " ".join(str(model or "").split())
    if not name:
        return ""
    params: dict[str, str] = {"q": name}
    if identity_token:
        params["identity"] = identity_token
    if exact_company:
        params["exact"] = "1"
    root = _clean_base(base) if base else app_base_url()
    return f"{root or PRODUCTION_APP_URL}?{urlencode(params, quote_via=quote, safe='')}"
