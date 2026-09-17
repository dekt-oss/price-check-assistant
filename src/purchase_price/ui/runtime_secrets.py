from __future__ import annotations

import os
from collections.abc import Mapping

import streamlit as st

from purchase_price.config import get_settings

_R2_SECRET_NAMES = (
    "R2_ACCOUNT_ID",
    "R2_BUCKET_NAME",
    "R2_BUCKET",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_ENDPOINT_URL",
)


def _mapping_value(mapping: Mapping[str, object], *keys: str) -> object | None:
    for key in keys:
        value = mapping.get(key)
        if value is not None and str(value).strip():
            return value
    return None


def hydrate_streamlit_runtime_secrets() -> tuple[str, ...]:
    """Expose configured Streamlit R2 secrets to pydantic-settings without leaking values.

    Streamlit normally exposes root-level secrets as environment variables. Some deployments keep
    the same values under an ``[r2]`` table instead. The service layer intentionally knows nothing
    about Streamlit, so normalize both layouts at the UI boundary before ``Settings`` is resolved.
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
    for env_name in _R2_SECRET_NAMES:
        if os.getenv(env_name, "").strip():
            continue
        lower_name = env_name.casefold()
        value = _mapping_value(root, env_name, lower_name)
        if value is None:
            value = _mapping_value(nested, env_name, lower_name)
        if value is None:
            continue
        os.environ[env_name] = str(value).strip()
        hydrated.append(env_name)

    if hydrated:
        get_settings.cache_clear()
    return tuple(hydrated)
