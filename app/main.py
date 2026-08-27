"""
FastAPI application entrypoint. Registers middleware, exception
handlers, and every module's router under one versioned API prefix —
this is the only file that knows about every module at once.
"""

from fastapi import FastAPI

# Registers every model with SQLAlchemy's mapper before anything else touches the ORM.
from app.core import model_registry  # noqa: F401
from app.config import get_settings
from app.exceptions import register_exception_handlers
from app.logging_config import configure_logging
from app.middleware import register_middleware

# ---- Routers ----
from app.modules.config_engine.router import router as config_engine_router
from app.modules.events.router import router as events_router
from app.modules.funnels.router import router as funnels_router
from app.modules.guardians.router import router as guardians_router
from app.modules.identity.router import router as identity_router
from app.modules.media.router import media_router, router as media_router_by_event
from app.modules.assistance.router import router as assistance_router
from app.modules.notifications.router import router as notifications_router, templates_router as notification_templates_router
from app.modules.payments.router import refunds_router, router as payments_router
from app.modules.registrations.router import router as registrations_router
from app.modules.organizations.router import router as organizations_router
from app.modules.rbac.router import router as rbac_router
from app.modules.staff.router import accept_router as staff_accept_router, router as staff_router
from app.modules.referrals.router import router as referrals_router
from app.modules.teams.router import router as teams_router
from app.modules.tickets.router import checkins_router, router as tickets_router
from app.modules.reports.router import router as reports_router
from app.modules.audit_log.router import router as audit_log_router


settings = get_settings()

configure_logging(settings.environment)

app = FastAPI(title=settings.app_name)

register_middleware(app)
register_exception_handlers(app)


# ---- Routers ----

app.include_router(
    identity_router,
    prefix=settings.api_v1_prefix,
)

app.include_router(
    rbac_router,
    prefix=settings.api_v1_prefix,
)

app.include_router(
    organizations_router,
    prefix=settings.api_v1_prefix,
)

app.include_router(
    events_router,
    prefix=settings.api_v1_prefix,
)

app.include_router(
    registrations_router,
    prefix=settings.api_v1_prefix,
)

app.include_router(
    teams_router,
    prefix=settings.api_v1_prefix,
)

app.include_router(
    guardians_router,
    prefix=settings.api_v1_prefix,
)

app.include_router(
    config_engine_router,
    prefix=settings.api_v1_prefix,
)

app.include_router(
    funnels_router,
    prefix=settings.api_v1_prefix,
)

app.include_router(
    payments_router,
    prefix=settings.api_v1_prefix,
)

app.include_router(
    refunds_router,
    prefix=settings.api_v1_prefix,
)

app.include_router(
    tickets_router,
    prefix=settings.api_v1_prefix,
)

app.include_router(
    checkins_router,
    prefix=settings.api_v1_prefix,
)

app.include_router(
    media_router_by_event,
    prefix=settings.api_v1_prefix,
)

app.include_router(
    media_router,
    prefix=settings.api_v1_prefix,
)

app.include_router(
    notifications_router,
    prefix=settings.api_v1_prefix,
)

app.include_router(
    notification_templates_router,
    prefix=settings.api_v1_prefix,
)

app.include_router(
    staff_router,
    prefix=settings.api_v1_prefix,
)

app.include_router(
    staff_accept_router,
    prefix=settings.api_v1_prefix,
)

app.include_router(
    referrals_router,
    prefix=settings.api_v1_prefix,
)

app.include_router(
    assistance_router,
    prefix=settings.api_v1_prefix,
)

app.include_router(
    reports_router,
    prefix=settings.api_v1_prefix,
)

app.include_router(
    audit_log_router,
    prefix=settings.api_v1_prefix,
)


@app.get("/health", tags=["meta"])
async def health_check() -> dict[str, str]:
    return {"status": "ok"}