"""Request logging + CORS configuration."""
import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from app.config import get_settings

logger = logging.getLogger("request")


def register_middleware(app: FastAPI) -> None:
    settings = get_settings()
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
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        request_id = str(uuid.uuid4())
        start = time.monotonic()
        response = await call_next(request)
        duration_ms = (time.monotonic() - start) * 1000
        logger.info(
            "request_id=%s method=%s path=%s status=%s duration_ms=%.1f",
            request_id, request.method, request.url.path, response.status_code, duration_ms,
        )
        response.headers["X-Request-ID"] = request_id
        return response
