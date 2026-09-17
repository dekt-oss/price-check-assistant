from __future__ import annotations

import os
from collections.abc import Mapping

import streamlit as st

from purchase_price.config import get_settings

_R2_SECRET_ALIASES: dict[str, tuple[str, ...]] = {
    "R2_ACCOUNT_ID": ("R2_ACCOUNT_ID", "r2_account_id", "account_id"),
    "R2_BUCKET_NAME": ("R2_BUCKET_NAME", "r2_bucket_name", "bucket_name"),
    "R2_BUCKET": ("R2_BUCKET", "r2_bucket", "bucket"),
    "R2_ACCESS_KEY_ID": ("R2_ACCESS_KEY_ID", "r2_access_key_id", "access_key_id"),
    "R2_SECRET_ACCESS_KEY": (
        "R2_SECRET_ACCESS_KEY",
        "r2_secret_access_key",
        "secret_access_key",
    ),
    "R2_ENDPOINT_URL": ("R2_ENDPOINT_URL", "r2_endpoint_url", "endpoint_url"),
}
_R2_SECRET_NAMES = tuple(_R2_SECRET_ALIASES)


def _mapping_value(mapping: Mapping[str, object], *keys: str) -> object | None:
    for key in keys:
        value = mapping.get(key)
        if value is not None and str(value).strip():
            return value
    return None


def hydrate_streamlit_runtime_secrets() -> tuple[str, ...]:
    """Expose configured Streamlit R2 secrets to pydantic-settings without leaking values.

    Streamlit normally exposes root-level secrets as environment variables. Some deployments keep
    the same values under an ``[r2]`` table instead, commonly with short names such as
    ``account_id`` and ``access_key_id``. The service layer intentionally knows nothing about
    Streamlit, so normalize supported layouts at the UI boundary before ``Settings`` is resolved.
    Existing environment variables always win.
    """

    try:
        root = st.secrets
    except (FileNotFoundError, KeyError):
        return ()

    nested: Mapping[str, object] = {}
    try:
        candidate = root.get("r2")
    except (KeyError, TypeError):
        candidate = None
    if isinstance(candidate, Mapping):
        nested = candidate

    hydrated: list[str] = []
    for env_name, aliases in _R2_SECRET_ALIASES.items():
        if os.getenv(env_name, "").strip():
            continue
        value = _mapping_value(root, *aliases)
        if value is None:
            value = _mapping_value(nested, *aliases)
        if value is None:
            continue
        os.environ[env_name] = str(value).strip()
        hydrated.append(env_name)

    if hydrated:
        get_settings.cache_clear()
    return tuple(hydrated)
