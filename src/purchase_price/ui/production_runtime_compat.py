from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import is_dataclass, replace
from inspect import signature
from threading import Lock
from types import FunctionType, SimpleNamespace
from typing import Any

_MFDS_AUTH_MARKERS = (
    "SERVICE_KEY_IS_NOT_REGISTERED_ERROR",
    "SERVICE_ACCESS_DENIED_ERROR",
    "PERMISSION_DENIED",
    "CODE=30",
)
_DISCOVERY_RELOAD_LOCK = Lock()


def _is_authorization_error_text(value: object) -> bool:
    text = str(value or "").upper()
    return any(marker in text for marker in _MFDS_AUTH_MARKERS)


def _copy_with_status(result: object, status: str) -> object:
    if is_dataclass(result):
        try:
            return replace(result, status=status)
        except (TypeError, ValueError):
            pass

    values = dict(getattr(result, "__dict__", {}) or {})
    values["status"] = status
    if values:
        return SimpleNamespace(**values)
    return SimpleNamespace(status=status)


def normalize_mfds_recall_lookup(result: object) -> object:
    """Recover authorization semantics when Streamlit retained an older recall helper."""

    if str(getattr(result, "status", "") or "") != "failure":
        return result

    error_text = " ".join(
        str(value or "")
        for value in (
            getattr(result, "error_type", ""),
            getattr(result, "error_message", ""),
        )
    )
    if not _is_authorization_error_text(error_text):
        return result
    return _copy_with_status(result, "not_authorized")


def mfds_recall_exception_result(
    exc: Exception,
    *,
    model_name: str,
    product_name: str,
) -> object:
    """Convert an uncaught legacy recall exception into an explicit Safety source state."""

    return SimpleNamespace(
        status="not_authorized" if _is_authorization_error_text(exc) else "failure",
        query_type="model" if model_name else "product",
        query=model_name or product_name,
        records=(),
        error_type=type(exc).__name__,
        error_message=str(exc),
        checked_at=None,
        source_url=None,
    )


def _supports_keyword(function: Callable[..., Any], keyword: str) -> bool:
    try:
        return keyword in signature(function).parameters
    except (TypeError, ValueError):
        return False


def _guard_contract_enrichment(
    original: Callable[..., Any],
) -> Callable[..., Any]:
    supports_defer_flag = _supports_keyword(original, "allow_independent_search")

    def guarded(*args: Any, **kwargs: Any) -> Any:
        kwargs = dict(kwargs)
        timeout = kwargs.get("timeout_seconds")
        if timeout is not None:
            kwargs["timeout_seconds"] = min(float(timeout), 12.0)
        if "max_retries" in kwargs:
            kwargs["max_retries"] = min(int(kwargs["max_retries"]), 1)

        if supports_defer_flag:
            kwargs["allow_independent_search"] = False
        else:
            # Legacy helpers predate the explicit DEFERRED state. Removing only the independent
            # product-name terms preserves bid-linked contracts while preventing the slow broad
            # date-range fallback (and code=07) from blocking the synchronous workspace.
            kwargs["independent_terms"] = ()
            kwargs.pop("allow_independent_search", None)
        return original(*args, **kwargs)

    return guarded


def _fresh_discovery_function(
    original: Callable[..., Any],
) -> Callable[..., Any]:
    """Load the bounded-concurrency Shopping Research implementation after a hot deployment."""

    try:
        module = importlib.import_module(
            "purchase_price.services.g2b_unmapped_discovery"
        )
    except Exception:
        return original

    current = getattr(module, "discover_unmapped_g2b_candidates", original)
    current_globals = getattr(current, "__globals__", {})
    if "G2B_DISCOVERY_MAX_WORKERS" in current_globals:
        return current

    with _DISCOVERY_RELOAD_LOCK:
        try:
            importlib.invalidate_caches()
            module = importlib.import_module(
                "purchase_price.services.g2b_unmapped_discovery"
            )
            if not hasattr(module, "G2B_DISCOVERY_MAX_WORKERS"):
                # Reload only the leaf Research module. Reloading shared transport modules can
                # replace exception-class objects that older Streamlit imports still reference.
                module = importlib.reload(module)
            refreshed = getattr(module, "discover_unmapped_g2b_candidates", None)
            return refreshed if callable(refreshed) else original
        except Exception:
            return original


def _guard_discovery(
    original: Callable[..., Any],
) -> Callable[..., Any]:
    current = _fresh_discovery_function(original)

    def guarded(*args: Any, **kwargs: Any) -> Any:
        kwargs = dict(kwargs)
        timeout = kwargs.get("timeout_seconds")
        if timeout is not None:
            kwargs["timeout_seconds"] = min(float(timeout), 12.0)
        if "max_retries" in kwargs:
            kwargs["max_retries"] = min(int(kwargs["max_retries"]), 1)
        return current(*args, **kwargs)

    return guarded


def run_market_research_hot_reload_safe(
    runner: Callable[..., Any],
    query: Any,
    **kwargs: Any,
) -> Any:
    """Run the synchronous Research path without trusting cached helper function objects.

    Streamlit Cloud can re-execute the page while keeping imported helper modules in sys.modules.
    Clone the page-visible runner with request-local globals so stale helpers cannot re-enable the
    slow independent contract scan. When the Shopping discovery helper is stale, refresh only that
    bounded-concurrency module chain rather than reloading evidence-domain enums globally.
    """

    if not isinstance(runner, FunctionType):
        return runner(query, **kwargs)

    runtime_globals = dict(runner.__globals__)
    contract = runtime_globals.get("enrich_market_bundle_with_contracts")
    if callable(contract):
        runtime_globals["enrich_market_bundle_with_contracts"] = _guard_contract_enrichment(
            contract
        )

    discovery = runtime_globals.get("discover_unmapped_g2b_candidates")
    if callable(discovery):
        runtime_globals["discover_unmapped_g2b_candidates"] = _guard_discovery(discovery)

    compatible = FunctionType(
        runner.__code__,
        runtime_globals,
        name=runner.__name__,
        argdefs=runner.__defaults__,
        closure=runner.__closure__,
    )
    compatible.__kwdefaults__ = getattr(runner, "__kwdefaults__", None)
    compatible.__annotations__ = getattr(runner, "__annotations__", {})
    return compatible(query, **kwargs)
