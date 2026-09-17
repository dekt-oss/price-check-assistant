from types import SimpleNamespace

from purchase_price.config import get_settings
from purchase_price.ui import runtime_secrets


def _clear_r2_env(monkeypatch) -> None:
    for name in runtime_secrets._R2_SECRET_NAMES:
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()


def test_hydrate_streamlit_runtime_secrets_accepts_nested_r2_table(monkeypatch) -> None:
    _clear_r2_env(monkeypatch)
    fake_streamlit = SimpleNamespace(
        secrets={
            "r2": {
                "r2_account_id": "account",
                "r2_bucket": "bucket",
                "r2_access_key_id": "access",
                "r2_secret_access_key": "secret",
            }
        }
    )
    monkeypatch.setattr(runtime_secrets, "st", fake_streamlit)

    hydrated = runtime_secrets.hydrate_streamlit_runtime_secrets()

    assert set(hydrated) == {
        "R2_ACCOUNT_ID",
        "R2_BUCKET",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
    }
    assert get_settings().r2_configured is True


def test_hydrate_streamlit_runtime_secrets_does_not_override_environment(monkeypatch) -> None:
    _clear_r2_env(monkeypatch)
    monkeypatch.setenv("R2_ACCOUNT_ID", "env-account")
    fake_streamlit = SimpleNamespace(secrets={"R2_ACCOUNT_ID": "secret-account"})
    monkeypatch.setattr(runtime_secrets, "st", fake_streamlit)

    runtime_secrets.hydrate_streamlit_runtime_secrets()

    assert get_settings().r2_account_id == "env-account"
