"""Request logging + CORS configuration."""
import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from app.config import get_settings
from app.core.discovery_updates import notify_discovery_change

logger = logging.getLogger("request")


def register_middleware(app: FastAPI) -> None:
    settings = get_settings()
    is_development = settings.environment.lower() in {"development", "dev", "test", "local"}
    allowed_origins = [origin.strip() for origin in settings.cors_allowed_origins.split(",") if origin.strip()]
    if settings.environment.lower() in {"production", "prod"} and "*" in allowed_origins:
        raise RuntimeError("Wildcard CORS origins are not allowed in production.")
    if settings.environment.lower() in {"production", "prod"} and not allowed_origins:
        raise RuntimeError("CORS_ALLOWED_ORIGINS must be configured in production.")
    if settings.environment.lower() in {"production", "prod"} and not settings.trusted_hosts.strip():
        raise RuntimeError("TRUSTED_HOSTS must be configured in production.")
    if settings.trusted_hosts.strip():
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=[host.strip() for host in settings.trusted_hosts.split(",") if host.strip()],
        )
    app.add_middleware(
        CORSMiddleware,
        # Local development may use a browser, emulator bridge, or a
        # dynamically assigned dev-server port. Accept those origins only
        # outside production; production remains explicitly allow-listed.
        allow_origins=["*"] if is_development else allowed_origins,
        allow_origin_regex=None,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Accept",
            "X-Request-ID",
            "X-Device-ID",
            "X-Client-Version",
        ],
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        request_id = str(uuid.uuid4())
        start = time.monotonic()
        response = await call_next(request)
        await notify_discovery_change(request.method, request.url.path, response.status_code)
        duration_ms = (time.monotonic() - start) * 1000
        logger.info(
            "request_id=%s method=%s path=%s status=%s duration_ms=%.1f",
            request_id, request.method, request.url.path, response.status_code, duration_ms,
        )
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(self), microphone=(), geolocation=()"
        if settings.environment.lower() in {"production", "prod"}:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response
