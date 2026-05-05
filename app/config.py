from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    SUPABASE_URL: str
    SUPABASE_SECRET_KEY: str

    # RevenueCat webhook — paste REVENUECAT_WEBHOOK_PUBLIC_URL into RevenueCat → Integrations → Webhooks
    REVENUECAT_WEBHOOK_PUBLIC_URL: str | None = None
    # Optional: exact Authorization header RevenueCat sends (dashboard “Authorization header value”)
    REVENUECAT_WEBHOOK_AUTHORIZATION: str | None = None
    # Must match RevenueCat entitlement id (and mobile EXPO_PUBLIC_REVENUECAT_ENTITLEMENT_ID)
    REVENUECAT_ENTITLEMENT_ID: str = "pro"


@lru_cache
def get_settings() -> Settings:
    return Settings()
