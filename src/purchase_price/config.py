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
    # Shared key alias used for approved market/public-data APIs.
    data_go_kr_market_service_key: str | None = None

    # MFDS key. Source-specific wins over shared/legacy.
    mfds_service_key: str | None = None

    # Historical G2B key name. Existing deployments often used this for ShoppingMall API.
    # Research APIs can be approved under a different data.go.kr service subscription, so the
    # shopping and research families must not be forced to share one key.
    g2b_service_key: str | None = None
    g2b_shopping_service_key: str | None = None
    g2b_research_service_key: str | None = None
    # Contract authorization is subscription-specific. A key that works for bid/award/pre-spec can
    # still return SERVICE_KEY_IS_NOT_REGISTERED_ERROR for CntrctInfoService, so keep it independent.
    g2b_contract_service_key: str | None = None
    # Newly approved PPS services are kept separate because data.go.kr authorization is
    # subscription-specific even when the encoded key text happens to be identical.
    g2b_catalog_service_key: str | None = None
    g2b_lifecycle_service_key: str | None = None

    g2b_shopping_base_url: str | None = None
    g2b_contract_base_url: str | None = None
    g2b_catalog_base_url: str | None = None
    g2b_lifecycle_base_url: str | None = None
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

        Preserve the historical G2B_SERVICE_KEY precedence for shopping so existing deployments do
        not silently switch away from the key that was actually approved for the shopping service.
        """

        return (
            self.g2b_shopping_service_key
            or self.g2b_service_key
            or self.data_go_kr_market_service_key
            or self.data_go_kr_service_key
        )

    @property
    def resolved_g2b_research_service_key(self) -> str | None:
        """Resolve the key for bid/award/pre-spec/item research APIs."""

        return (
            self.g2b_research_service_key
            or self.data_go_kr_market_service_key
            or self.g2b_service_key
            or self.data_go_kr_service_key
        )

    @property
    def resolved_g2b_contract_service_key(self) -> str | None:
        """Resolve the key for CntrctInfoService without assuming bid Research authorization.

        Prefer a dedicated contract subscription. The shared market key is intentionally checked
        before the general Research key because live validation has shown a Research key can be
        authorized for bid/award/pre-spec yet unregistered for the contract service.
        """

        return (
            self.g2b_contract_service_key
            or self.data_go_kr_market_service_key
            or self.g2b_research_service_key
            or self.g2b_service_key
            or self.data_go_kr_service_key
        )

    @property
    def resolved_g2b_catalog_service_key(self) -> str | None:
        """Resolve the key for PPS Thing List / official catalog attributes."""

        return (
            self.g2b_catalog_service_key
            or self.data_go_kr_market_service_key
            or self.g2b_research_service_key
            or self.g2b_service_key
            or self.data_go_kr_service_key
        )

    @property
    def resolved_g2b_lifecycle_service_key(self) -> str | None:
        """Resolve the key for the integrated procurement lifecycle service."""

        return (
            self.g2b_lifecycle_service_key
            or self.data_go_kr_market_service_key
            or self.g2b_research_service_key
            or self.g2b_service_key
            or self.data_go_kr_service_key
        )

    @property
    def resolved_g2b_service_key(self) -> str | None:
        """Backward-compatible alias for callers that specifically use the shopping API."""

        return self.resolved_g2b_shopping_service_key

    @property
    def g2b_shopping_key_source(self) -> str:
        return self._key_source(
            (
                ("G2B_SHOPPING_SERVICE_KEY", self.g2b_shopping_service_key),
                ("G2B_SERVICE_KEY", self.g2b_service_key),
                ("DATA_GO_KR_MARKET_SERVICE_KEY", self.data_go_kr_market_service_key),
                ("DATA_GO_KR_SERVICE_KEY", self.data_go_kr_service_key),
            )
        )

    @property
    def g2b_research_key_source(self) -> str:
        return self._key_source(
            (
                ("G2B_RESEARCH_SERVICE_KEY", self.g2b_research_service_key),
                ("DATA_GO_KR_MARKET_SERVICE_KEY", self.data_go_kr_market_service_key),
                ("G2B_SERVICE_KEY", self.g2b_service_key),
                ("DATA_GO_KR_SERVICE_KEY", self.data_go_kr_service_key),
            )
        )

    @property
    def g2b_contract_key_source(self) -> str:
        return self._key_source(
            (
                ("G2B_CONTRACT_SERVICE_KEY", self.g2b_contract_service_key),
                ("DATA_GO_KR_MARKET_SERVICE_KEY", self.data_go_kr_market_service_key),
                ("G2B_RESEARCH_SERVICE_KEY", self.g2b_research_service_key),
                ("G2B_SERVICE_KEY", self.g2b_service_key),
                ("DATA_GO_KR_SERVICE_KEY", self.data_go_kr_service_key),
            )
        )

    @property
    def g2b_catalog_key_source(self) -> str:
        return self._key_source(
            (
                ("G2B_CATALOG_SERVICE_KEY", self.g2b_catalog_service_key),
                ("DATA_GO_KR_MARKET_SERVICE_KEY", self.data_go_kr_market_service_key),
                ("G2B_RESEARCH_SERVICE_KEY", self.g2b_research_service_key),
                ("G2B_SERVICE_KEY", self.g2b_service_key),
                ("DATA_GO_KR_SERVICE_KEY", self.data_go_kr_service_key),
            )
        )

    @property
    def g2b_lifecycle_key_source(self) -> str:
        return self._key_source(
            (
                ("G2B_LIFECYCLE_SERVICE_KEY", self.g2b_lifecycle_service_key),
                ("DATA_GO_KR_MARKET_SERVICE_KEY", self.data_go_kr_market_service_key),
                ("G2B_RESEARCH_SERVICE_KEY", self.g2b_research_service_key),
                ("G2B_SERVICE_KEY", self.g2b_service_key),
                ("DATA_GO_KR_SERVICE_KEY", self.data_go_kr_service_key),
            )
        )

    @staticmethod
    def _key_source(values: tuple[tuple[str, str | None], ...]) -> str:
        for name, value in values:
            if value and value.strip():
                return name
        return "미설정"


@lru_cache
def get_settings() -> Settings:
    return Settings()
