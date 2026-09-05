from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "dev"
    database_url: str = (
        "postgresql+psycopg://purchase_user:purchase_pass@localhost:5432/purchase_price"
    )
    log_level: str = "INFO"

    # Legacy/common key kept for backward compatibility with the original public-data setup.
    data_go_kr_service_key: str | None = None
    # Shared key alias used for the currently approved market/public-data APIs. This may be the
    # same issued key across multiple data.go.kr services; source-specific keys still take
    # precedence if they are configured later.
    data_go_kr_market_service_key: str | None = None
    # Source-specific keys take precedence when configured. They may currently have the same
    # value, but keeping them separate avoids breaking older approved APIs when a key changes.
    mfds_service_key: str | None = None
    g2b_service_key: str | None = None

    g2b_shopping_base_url: str | None = None
    g2b_contract_base_url: str | None = None
    g2b_request_timeout_seconds: float = 20.0
    g2b_max_retries: int = 3

    mfds_model_info_base_url: str | None = None
    mfds_business_license_base_url: str | None = None
    mfds_udi_code_base_url: str | None = None
    mfds_request_timeout_seconds: float = 20.0
    mfds_max_retries: int = 3

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def resolved_mfds_service_key(self) -> str | None:
        return (
            self.mfds_service_key
            or self.data_go_kr_market_service_key
            or self.data_go_kr_service_key
        )

    @property
    def resolved_g2b_service_key(self) -> str | None:
        return (
            self.g2b_service_key
            or self.data_go_kr_market_service_key
            or self.data_go_kr_service_key
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
