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
    # same issued key across multiple data.go.kr services.
    data_go_kr_market_service_key: str | None = None

    # MFDS key. A source-specific key wins over shared/legacy keys.
    mfds_service_key: str | None = None

    # Historical G2B key name. In early deployments this was issued for the ShoppingMall API and
    # can differ from the newer bid/award/pre-spec service subscription key. Keep it for backward
    # compatibility, but do not force the same key onto every G2B API family.
    g2b_service_key: str | None = None
    g2b_shopping_service_key: str | None = None
    g2b_research_service_key: str | None = None

    g2b_shopping_base_url: str | None = None
    g2b_contract_base_url: str | None = None
    g2b_request_timeout_seconds: float = 20.0
    g2b_max_retries: int = 3
    g2b_search_request_budget: int = 120

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
    def resolved_g2b_shopping_service_key(self) -> str | None:
        """Resolve the key for ShoppingMallPrdctInfoService.

        Existing deployments often placed the older shopping-service key in G2B_SERVICE_KEY, so
        that value remains ahead of the newer shared market key for shopping calls.
        """

        return (
            self.g2b_shopping_service_key
            or self.g2b_service_key
            or self.data_go_kr_market_service_key
            or self.data_go_kr_service_key
        )

    @property
    def resolved_g2b_research_service_key(self) -> str | None:
        """Resolve the key for bid/award/pre-spec/item/contract research APIs.

        The newer research APIs can be approved under a different service subscription than the
        older shopping API. Prefer the dedicated research key and then the shared market key before
        falling back to the historical G2B key. This prevents a valid but wrong-service shopping
        key from masking the newly approved research key and causing code-30 auth failures.
        """

        return (
            self.g2b_research_service_key
            or self.data_go_kr_market_service_key
            or self.g2b_service_key
            or self.data_go_kr_service_key
        )

    @property
    def resolved_g2b_service_key(self) -> str | None:
        """Backward-compatible alias for callers that specifically use the shopping API."""

        return self.resolved_g2b_shopping_service_key

    @property
    def g2b_shopping_key_source(self) -> str:
        for name, value in (
            ("G2B_SHOPPING_SERVICE_KEY", self.g2b_shopping_service_key),
            ("G2B_SERVICE_KEY", self.g2b_service_key),
            ("DATA_GO_KR_MARKET_SERVICE_KEY", self.data_go_kr_market_service_key),
            ("DATA_GO_KR_SERVICE_KEY", self.data_go_kr_service_key),
        ):
            if value:
                return name
        return "미설정"

    @property
    def g2b_research_key_source(self) -> str:
        for name, value in (
            ("G2B_RESEARCH_SERVICE_KEY", self.g2b_research_service_key),
            ("DATA_GO_KR_MARKET_SERVICE_KEY", self.data_go_kr_market_service_key),
            ("G2B_SERVICE_KEY", self.g2b_service_key),
            ("DATA_GO_KR_SERVICE_KEY", self.data_go_kr_service_key),
        ):
            if value:
                return name
        return "미설정"


@lru_cache
def get_settings() -> Settings:
    return Settings()
