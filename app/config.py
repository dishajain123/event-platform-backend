"""
Centralized application settings.

Every environment variable the app needs is declared here, typed, and
validated once at startup — nothing reads from os.environ directly
anywhere else in the codebase.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ---- App ----
    environment: str = "development"
    app_name: str = "event-platform-backend"
    api_v1_prefix: str = "/api/v1"

    # ---- Database ----
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/event_platform"

    # ---- Redis ----
    redis_url: str = "redis://localhost:6379/0"

    # ---- Payments / Tickets ----
    payment_gateway_provider: str = "razorpay"
    payment_gateway_key_id: str = "rzp_test_key"
    payment_gateway_key_secret: str = "dev-secret"
    ticket_qr_secret: str = "change-this-ticket-secret"

    # ---- Auth / JWT ----
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 30

    # ---- OTP ----
    otp_length: int = 6
    otp_expiry_seconds: int = 300
    otp_resend_cooldown_seconds: int = 30
    otp_max_verify_attempts: int = 5
    otp_hash_pepper: str = "change-this-too"

    # ---- Identity document encryption ----
    identity_doc_encryption_key: str = ""

    # ---- SMS provider ----
    sms_provider_api_key: str = ""
    sms_provider_api_url: str = ""
    sms_provider_sender_id: str = "EVENTPLAT"
    sms_provider_timeout_seconds: float = 10.0


@lru_cache
def get_settings() -> Settings:
    """Settings are read once and cached — every part of the app shares one instance."""
    return Settings()
