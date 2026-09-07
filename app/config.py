"""
Centralized application settings.

Every environment variable the app needs is declared here, typed, and
validated once at startup — nothing reads from os.environ directly
anywhere else in the codebase.
"""
from functools import lru_cache

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ---- App ----
    environment: str = "development"
    app_name: str = "event-platform-backend"
    api_v1_prefix: str = "/api/v1"
    cors_allowed_origins: str = "http://localhost:3000,http://localhost:5173"
    trusted_hosts: str = ""

    # ---- Database ----
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/event_platform"

    # ---- Redis ----
    redis_url: str = "redis://localhost:6379/0"

    # ---- Payments / Tickets ----
    payment_gateway_provider: str = "razorpay"
    payment_gateway_key_id: str = "rzp_test_key"
    payment_gateway_key_secret: str = "dev-secret"
    payment_gateway_api_url: str = "https://api.razorpay.com"
    payment_gateway_webhook_secret: str = "dev-webhook-secret"
    payment_reconciliation_interval_seconds: int = 300
    payment_reconciliation_stale_seconds: int = 1800
    payment_reconciliation_batch_size: int = 100
    # Keep the old environment name as a migration alias for deployed secrets.
    ticket_barcode_secret: str = Field(
        default="change-this-ticket-secret",
        validation_alias=AliasChoices("TICKET_BARCODE_SECRET", "TICKET_QR_SECRET"),
    )

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
    otp_ip_cooldown_seconds: int = 10
    otp_ip_max_requests_per_window: int = 10
    otp_global_max_requests_per_window: int = 1000
    otp_rate_limit_window_seconds: int = 60

    # ---- Identity document encryption ----
    identity_doc_encryption_key: str = ""

    # ---- Object storage (MinIO) ----
    minio_endpoint: str = ""
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "event-platform-media"
    minio_secure: bool = False
    minio_public_base_url: str = ""
    media_max_bytes: int = 10 * 1024 * 1024
    allow_local_storage_fallback: bool = False

    # ---- SMS provider ----
    sms_provider_api_key: str = ""
    sms_provider_api_url: str = ""
    sms_provider_sender_id: str = "EVENTPLAT"
    sms_provider_timeout_seconds: float = 10.0

    # ---- Notification providers ----
    notification_push_provider: str = "development"
    notification_push_api_url: str = ""
    notification_push_api_key: str = ""
    notification_email_provider: str = "development"
    notification_email_api_url: str = ""
    notification_email_api_key: str = ""
    notification_email_from: str = ""
    notification_provider_timeout_seconds: float = 10.0
    notification_max_attempts: int = 3
    notification_timezone: str = "UTC"

    @model_validator(mode="after")
    def validate_production_configuration(self):
        if self.environment.lower() not in {"production", "prod"}:
            return self
        placeholders = {
            "PAYMENT_GATEWAY_KEY_ID": self.payment_gateway_key_id in {"", "rzp_test_key"},
            "PAYMENT_GATEWAY_KEY_SECRET": self.payment_gateway_key_secret in {"", "dev-secret"},
            "PAYMENT_GATEWAY_WEBHOOK_SECRET": self.payment_gateway_webhook_secret in {"", "dev-webhook-secret"},
            "TICKET_BARCODE_SECRET": self.ticket_barcode_secret in {"", "change-this-ticket-secret", "change-this-too"},
            "OTP_HASH_PEPPER": self.otp_hash_pepper in {"", "change-this-too"},
            "MINIO_ENDPOINT": not bool(self.minio_endpoint.strip()),
        }
        missing = [name for name, invalid in placeholders.items() if invalid]
        if missing:
            raise ValueError(f"Production configuration contains missing or placeholder secrets: {', '.join(missing)}")
        return self


@lru_cache
def get_settings() -> Settings:
    """Settings are read once and cached — every part of the app shares one instance."""
    return Settings()
