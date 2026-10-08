from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "dev"
    database_url: str = (
        "postgresql+psycopg://purchase_user:purchase_pass@localhost:5432/purchase_price"
    )
    log_level: str = "INFO"

    # Cloudflare R2 raw-evidence / backup object storage.
    # Keep credentials in deployment secrets only. The raw prefix is content-addressed and
    # intended for public procurement evidence only; private hospital purchasing data is excluded.
    r2_account_id: str | None = None
    r2_bucket_name: str | None = None
    # Compatibility alias for deployments that already use R2_BUCKET.
    r2_bucket: str | None = None
    r2_access_key_id: str | None = None
    r2_secret_access_key: str | None = None
    r2_endpoint_url: str | None = None
    r2_raw_prefix: str = "raw/v1"
    r2_backup_prefix: str = "db-backups/v1"
    # R2 Standard includes 10 GB-month free storage. Stay below that billing boundary with a
    # conservative 1 GB reserve. This value may only be lowered, never raised above 9 GB, so a
    # deployment cannot accidentally disable the zero-cost storage policy through configuration.
    r2_zero_cost_hard_limit_gb: float = Field(default=9.0, gt=0, le=9.0)
    r2_zero_cost_warn_limit_gb: float = Field(default=8.0, gt=0, le=8.0)

    # Legacy/common key kept for backward compatibility with the original public-data setup.
    data_go_kr_service_key: str | None = None
    # Shared key alias used for approved market/public-data APIs.
    data_go_kr_market_service_key: str | None = None

    # MFDS keys. Source-specific wins over shared/legacy.
    mfds_service_key: str | None = None
    # HIRA (건강보험심사평가원) 병원정보 / 의료기관별상세정보. Optional: the sync tries every data.go.kr
    # key when unset, because 활용신청 is tied to the account that owns the key.
    hira_service_key: str | None = None
    mfds_recall_service_key: str | None = None

    # Historical G2B key name. Existing deployments often used this for ShoppingMall API.
    # Research APIs can be approved under a different data.go.kr service subscription, so the
    # shopping and research families must not be forced to share one key.
    g2b_service_key: str | None = None
    g2b_shopping_service_key: str | None = None
    g2b_research_service_key: str | None = None
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
    mfds_product_info_base_url: str | None = None
    mfds_recall_base_url: str | None = None
    mfds_request_timeout_seconds: float = 20.0
    mfds_max_retries: int = 3

    # NAVER 뉴스 검색 API (병원 News Radar 탐지 전용). 검색결과는 제목·시간·링크 표시에만 쓰고
    # AI 입력·요약에는 쓰지 않는다 (2026-09-07 네이버 검색 API 이용약관).
    # Keys come from NAVER API HUB (NAVER Cloud Platform console). The legacy Developers
    # Center keys still work until 2027-06 when NAVER_API_STYLE=developers is set.
    naver_client_id: str | None = None
    naver_client_secret: str | None = None
    naver_api_style: str = "apihub"
    naver_news_base_url: str | None = None
    naver_request_timeout_seconds: float = 10.0
    # News Radar Phase 2: the collector job writes the article list to R2 (news/v1/). For a local
    # review without R2, point both the collector (--output) and the page at a local file.
    news_radar_index_path: str | None = None
    news_radar_status_path: str | None = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def resolved_r2_endpoint_url(self) -> str | None:
        if self.r2_endpoint_url and self.r2_endpoint_url.strip():
            return self.r2_endpoint_url.rstrip("/")
        if self.r2_account_id and self.r2_account_id.strip():
            return f"https://{self.r2_account_id}.r2.cloudflarestorage.com"
        return None

    @property
    def resolved_r2_bucket_name(self) -> str | None:
        for value in (self.r2_bucket_name, self.r2_bucket):
            if value and value.strip():
                return value.strip()
        return None

    @property
    def r2_configured(self) -> bool:
        return all(
            value and value.strip()
            for value in (
                self.resolved_r2_endpoint_url,
                self.resolved_r2_bucket_name,
                self.r2_access_key_id,
                self.r2_secret_access_key,
            )
        )

    @property
    def r2_zero_cost_hard_limit_bytes(self) -> int:
        # Cloudflare bills storage in decimal GB; use the same unit for the fail-closed guard.
        return int(self.r2_zero_cost_hard_limit_gb * 1_000_000_000)

    @property
    def r2_zero_cost_warn_limit_bytes(self) -> int:
        return int(self.r2_zero_cost_warn_limit_gb * 1_000_000_000)

    @property
    def naver_configured(self) -> bool:
        return bool(
            self.naver_client_id
            and self.naver_client_id.strip()
            and self.naver_client_secret
            and self.naver_client_secret.strip()
        )

    @property
    def resolved_mfds_service_key(self) -> str | None:
        return (
            self.mfds_service_key
            or self.data_go_kr_market_service_key
            or self.data_go_kr_service_key
        )

    @property
    def resolved_mfds_recall_service_key(self) -> str | None:
        """Resolve the key for the MFDS recall/sale-stop service.

        data.go.kr authorization is service-subscription specific. A general MFDS key may exist
        while the recall service is still unapproved, so deployments can provide a dedicated key.
        """

        return (
            self.mfds_recall_service_key
            or self.mfds_service_key
            or self.data_go_kr_market_service_key
            or self.data_go_kr_service_key
        )

    @property
    def mfds_recall_key_source(self) -> str:
        return self._key_source(
            (
                ("MFDS_RECALL_SERVICE_KEY", self.mfds_recall_service_key),
                ("MFDS_SERVICE_KEY", self.mfds_service_key),
                ("DATA_GO_KR_MARKET_SERVICE_KEY", self.data_go_kr_market_service_key),
                ("DATA_GO_KR_SERVICE_KEY", self.data_go_kr_service_key),
            )
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
        """Resolve the key for bid/award/pre-spec/item/contract research APIs.

        Prefer the dedicated research key and then the shared market key before falling back to the
        historical G2B key. A valid shopping-service key may be unregistered for these APIs.
        """

        return (
            self.g2b_research_service_key
            or self.data_go_kr_market_service_key
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
