from __future__ import annotations

import os
from collections.abc import Mapping

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from purchase_price.config import get_settings

_R2_SECRET_ALIASES: dict[str, tuple[str, ...]] = {
    "R2_ACCOUNT_ID": ("R2_ACCOUNT_ID", "r2_account_id", "account_id"),
    "R2_BUCKET_NAME": ("R2_BUCKET_NAME", "r2_bucket_name", "bucket_name"),
    "R2_BUCKET": ("R2_BUCKET", "r2_bucket", "bucket"),
    "R2_ACCESS_KEY_ID": (
        "R2_ACCESS_KEY_ID",
        "R2_READ_ACCESS_KEY_ID",
        "r2_access_key_id",
        "r2_read_access_key_id",
        "access_key_id",
    ),
    "R2_SECRET_ACCESS_KEY": (
        "R2_SECRET_ACCESS_KEY",
        "R2_READ_SECRET_ACCESS_KEY",
        "r2_secret_access_key",
        "r2_read_secret_access_key",
        "secret_access_key",
    ),
    "R2_ENDPOINT_URL": ("R2_ENDPOINT_URL", "r2_endpoint_url", "endpoint_url"),
}
_R2_SECRET_NAMES = tuple(_R2_SECRET_ALIASES)
_R2_NESTED_TABLE_NAMES = ("r2", "r2_read")

_PUBLIC_DATA_SECRET_ALIASES: dict[str, tuple[str, ...]] = {
    "DATA_GO_KR_SERVICE_KEY": ("DATA_GO_KR_SERVICE_KEY", "data_go_kr_service_key"),
    "DATA_GO_KR_MARKET_SERVICE_KEY": (
        "DATA_GO_KR_MARKET_SERVICE_KEY",
        "data_go_kr_market_service_key",
    ),
    "G2B_SERVICE_KEY": ("G2B_SERVICE_KEY", "g2b_service_key"),
    "G2B_SHOPPING_SERVICE_KEY": (
        "G2B_SHOPPING_SERVICE_KEY",
        "g2b_shopping_service_key",
    ),
    "G2B_RESEARCH_SERVICE_KEY": (
        "G2B_RESEARCH_SERVICE_KEY",
        "g2b_research_service_key",
    ),
    "G2B_CATALOG_SERVICE_KEY": ("G2B_CATALOG_SERVICE_KEY", "g2b_catalog_service_key"),
    "G2B_LIFECYCLE_SERVICE_KEY": (
        "G2B_LIFECYCLE_SERVICE_KEY",
        "g2b_lifecycle_service_key",
    ),
    "MFDS_SERVICE_KEY": ("MFDS_SERVICE_KEY", "mfds_service_key"),
    "MFDS_RECALL_SERVICE_KEY": (
        "MFDS_RECALL_SERVICE_KEY",
        "mfds_recall_service_key",
    ),
}
_PUBLIC_DATA_SECRET_NAMES = tuple(_PUBLIC_DATA_SECRET_ALIASES)
_PUBLIC_DATA_NESTED_TABLE_NAMES = ("api", "public_data", "data_go_kr")


def _mapping_value(mapping: Mapping[str, object], *keys: str) -> object | None:
    for key in keys:
        value = mapping.get(key)
        if value is not None and str(value).strip():
            return value
    return None


def _nested_secret_tables(
    root: Mapping[str, object],
    names: tuple[str, ...],
) -> tuple[Mapping[str, object], ...]:
    tables: list[Mapping[str, object]] = []
    for name in names:
        candidate = root.get(name)
        if isinstance(candidate, Mapping):
            tables.append(candidate)
    return tuple(tables)


def hydrate_streamlit_runtime_secrets() -> tuple[str, ...]:
    """Expose configured Streamlit R2 read credentials to pydantic-settings safely.

    The service layer intentionally knows nothing about Streamlit. Normalize supported Streamlit
    layouts at the UI boundary before ``Settings`` is resolved. Existing environment variables
    always win. Both the historical writer-style names and explicit read-only aliases are accepted,
    including ``[r2]`` and ``[r2_read]`` tables. This lets Production use a bucket-scoped read-only
    R2 token while GitHub collection/index workflows retain separate writer credentials.

    A deployment/test environment with no secrets file is valid and simply leaves the existing
    environment untouched. Secret values are never returned or logged.
    """

    try:
        root = st.secrets
        r2_tables = _nested_secret_tables(root, _R2_NESTED_TABLE_NAMES)
        public_data_tables = _nested_secret_tables(root, _PUBLIC_DATA_NESTED_TABLE_NAMES)
    except (FileNotFoundError, KeyError, TypeError, StreamlitSecretNotFoundError):
        return ()

    hydrated: list[str] = []
    groups = (
        (_R2_SECRET_ALIASES, r2_tables),
        (_PUBLIC_DATA_SECRET_ALIASES, public_data_tables),
    )
    for aliases_by_env, nested_tables in groups:
        for env_name, aliases in aliases_by_env.items():
            if os.getenv(env_name, "").strip():
                continue
            try:
                value = _mapping_value(root, *aliases)
            except StreamlitSecretNotFoundError:
                return tuple(hydrated)
            if value is None:
                for nested in nested_tables:
                    value = _mapping_value(nested, *aliases)
                    if value is not None:
                        break
            if value is None:
                continue
            os.environ[env_name] = str(value).strip()
            hydrated.append(env_name)

    if hydrated:
        get_settings.cache_clear()
    return tuple(hydrated)
