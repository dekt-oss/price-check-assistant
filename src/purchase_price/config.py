from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "dev"
    database_url: str = (
        "postgresql+psycopg://purchase_user:purchase_pass@localhost:5432/purchase_price"
    )
    log_level: str = "INFO"

    data_go_kr_service_key: str | None = None
    g2b_shopping_base_url: str | None = None
    g2b_contract_base_url: str | None = None
    g2b_request_timeout_seconds: float = 20.0
    g2b_max_retries: int = 3

    mfds_model_info_base_url: str | None = None
    mfds_business_license_base_url: str | None = None
    mfds_request_timeout_seconds: float = 20.0
    mfds_max_retries: int = 3

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
