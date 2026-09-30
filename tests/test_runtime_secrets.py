from types import SimpleNamespace

from purchase_price.config import get_settings
from purchase_price.ui import runtime_secrets


def _clear_r2_env(monkeypatch) -> None:
    for name in runtime_secrets._R2_SECRET_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("R2_READ_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("R2_READ_SECRET_ACCESS_KEY", raising=False)
    get_settings.cache_clear()


def _clear_public_data_env(monkeypatch) -> None:
    for name in runtime_secrets._PUBLIC_DATA_SECRET_NAMES:
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()


def test_hydrate_streamlit_runtime_secrets_accepts_nested_r2_table(monkeypatch) -> None:
    _clear_r2_env(monkeypatch)
    fake_streamlit = SimpleNamespace(
        secrets={
            "r2": {
                "account_id": "account",
                "bucket": "bucket",
                "access_key_id": "access",
                "secret_access_key": "secret",
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


def test_hydrate_streamlit_runtime_secrets_accepts_read_only_aliases(monkeypatch) -> None:
    _clear_r2_env(monkeypatch)
    fake_streamlit = SimpleNamespace(
        secrets={
            "r2_read": {
                "account_id": "account",
                "bucket": "bucket",
                "R2_READ_ACCESS_KEY_ID": "read-access",
                "R2_READ_SECRET_ACCESS_KEY": "read-secret",
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
    settings = get_settings()
    assert settings.r2_configured is True
    assert settings.r2_access_key_id == "read-access"
    assert settings.r2_secret_access_key == "read-secret"


def test_hydrate_streamlit_runtime_secrets_accepts_root_read_only_aliases(monkeypatch) -> None:
    _clear_r2_env(monkeypatch)
    fake_streamlit = SimpleNamespace(
        secrets={
            "R2_ACCOUNT_ID": "account",
            "R2_BUCKET": "bucket",
            "R2_READ_ACCESS_KEY_ID": "read-access",
            "R2_READ_SECRET_ACCESS_KEY": "read-secret",
        }
    )
    monkeypatch.setattr(runtime_secrets, "st", fake_streamlit)

    runtime_secrets.hydrate_streamlit_runtime_secrets()

    settings = get_settings()
    assert settings.r2_configured is True
    assert settings.r2_access_key_id == "read-access"
    assert settings.r2_secret_access_key == "read-secret"


def test_hydrate_streamlit_runtime_secrets_does_not_override_environment(monkeypatch) -> None:
    _clear_r2_env(monkeypatch)
    monkeypatch.setenv("R2_ACCOUNT_ID", "env-account")
    fake_streamlit = SimpleNamespace(secrets={"R2_ACCOUNT_ID": "secret-account"})
    monkeypatch.setattr(runtime_secrets, "st", fake_streamlit)

    runtime_secrets.hydrate_streamlit_runtime_secrets()

    assert get_settings().r2_account_id == "env-account"


def test_hydrate_streamlit_runtime_secrets_accepts_root_public_data_keys(monkeypatch) -> None:
    _clear_public_data_env(monkeypatch)
    fake_streamlit = SimpleNamespace(
        secrets={
            "G2B_RESEARCH_SERVICE_KEY": "g2b-research",
            "MFDS_RECALL_SERVICE_KEY": "mfds-recall",
        }
    )
    monkeypatch.setattr(runtime_secrets, "st", fake_streamlit)

    hydrated = runtime_secrets.hydrate_streamlit_runtime_secrets()

    assert set(hydrated) == {"G2B_RESEARCH_SERVICE_KEY", "MFDS_RECALL_SERVICE_KEY"}
    settings = get_settings()
    assert settings.g2b_research_service_key == "g2b-research"
    assert settings.mfds_recall_service_key == "mfds-recall"


def test_hydrate_streamlit_runtime_secrets_accepts_nested_api_keys(monkeypatch) -> None:
    _clear_public_data_env(monkeypatch)
    fake_streamlit = SimpleNamespace(
        secrets={
            "api": {
                "g2b_shopping_service_key": "g2b-shopping",
                "mfds_service_key": "mfds-model",
            }
        }
    )
    monkeypatch.setattr(runtime_secrets, "st", fake_streamlit)

    runtime_secrets.hydrate_streamlit_runtime_secrets()

    settings = get_settings()
    assert settings.g2b_shopping_service_key == "g2b-shopping"
    assert settings.mfds_service_key == "mfds-model"


def test_public_data_environment_still_wins_over_streamlit_secret(monkeypatch) -> None:
    _clear_public_data_env(monkeypatch)
    monkeypatch.setenv("MFDS_RECALL_SERVICE_KEY", "env-recall")
    fake_streamlit = SimpleNamespace(
        secrets={"MFDS_RECALL_SERVICE_KEY": "secret-recall"}
    )
    monkeypatch.setattr(runtime_secrets, "st", fake_streamlit)

    runtime_secrets.hydrate_streamlit_runtime_secrets()

    assert get_settings().mfds_recall_service_key == "env-recall"
