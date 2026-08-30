from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    environment: str = Field(default="development", alias="ENVIRONMENT")
    database_path: Path = Field(default=Path("data/catalog.sqlite3"), alias="DATABASE_PATH")
    cursor_secret: str = Field(default="development-only-change-me", alias="CURSOR_SECRET")
    cursor_ttl_seconds: int = Field(default=1800, alias="CURSOR_TTL_SECONDS", ge=60, le=86400)

    public_base_url: str = Field(default="https://nextlevelarena.it", alias="PUBLIC_BASE_URL")
    allowed_origins: str = Field(
        default="https://nextlevelarena.it,https://www.nextlevelarena.it,http://localhost:3000",
        alias="ALLOWED_ORIGINS",
    )

    require_app_proxy: bool = Field(default=False, alias="REQUIRE_APP_PROXY")
    shopify_app_secret: str | None = Field(default=None, alias="SHOPIFY_APP_SECRET")
    allowed_shop: str | None = Field(default=None, alias="ALLOWED_SHOP")
    app_proxy_max_age_seconds: int = Field(default=300, alias="APP_PROXY_MAX_AGE_SECONDS")

    rate_limit_per_minute: int = Field(default=120, alias="RATE_LIMIT_PER_MINUTE", ge=10)
    max_query_length: int = Field(default=120, alias="MAX_QUERY_LENGTH", ge=20, le=500)
    default_page_size: int = Field(default=24, alias="DEFAULT_PAGE_SIZE", ge=1, le=100)
    max_page_size: int = Field(default=60, alias="MAX_PAGE_SIZE", ge=1, le=100)

    auto_bootstrap: bool = Field(default=False, alias="AUTO_BOOTSTRAP")
    shopify_bulk_url: str | None = Field(default=None, alias="SHOPIFY_BULK_URL")
    shopify_shop: str | None = Field(default=None, alias="SHOPIFY_SHOP")
    shopify_admin_token: str | None = Field(default=None, alias="SHOPIFY_ADMIN_TOKEN")
    shopify_api_version: str = Field(default="2026-07", alias="SHOPIFY_API_VERSION")
    snapshot_path: Path = Field(default=Path("data/shopify-snapshot.jsonl"), alias="SNAPSHOT_PATH")
    expected_product_count: int | None = Field(default=None, alias="EXPECTED_PRODUCT_COUNT")

    @field_validator("environment")
    @classmethod
    def normalize_environment(cls, value: str) -> str:
        return value.strip().lower()

    @property
    def origin_list(self) -> list[str]:
        return [item.strip().rstrip("/") for item in self.allowed_origins.split(",") if item.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    def validate_security(self) -> None:
        if self.is_production and self.cursor_secret == "development-only-change-me":
            raise RuntimeError("CURSOR_SECRET must be replaced in production")
        if self.require_app_proxy and not self.shopify_app_secret:
            raise RuntimeError("SHOPIFY_APP_SECRET is required when REQUIRE_APP_PROXY=true")
        if self.require_app_proxy and not self.allowed_shop:
            raise RuntimeError("ALLOWED_SHOP is required when REQUIRE_APP_PROXY=true")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.validate_security()
    return settings
