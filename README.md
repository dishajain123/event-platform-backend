# Event Platform Backend

FastAPI backend and PostgreSQL persistence layer for the Event Platform. This service is the source of truth for authentication, roles, event configuration, registrations, payments, tickets, check-ins, refunds, feedback, sponsorships, volunteers, notifications, reports, and all event-scoped authorization.

## Prerequisites

- Python 3.12
- PostgreSQL 16 or compatible PostgreSQL
- Redis 7 or compatible Redis
- Optional MinIO/S3-compatible object storage for media and identity documents
- Razorpay credentials for real payment testing; development defaults are not production credentials

## Local Python Setup

```bash
cd /Users/dishajain/Desktop/event-platform-backend
python3.12 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

Set at least the following values in `.env`:

```env
ENVIRONMENT=development
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/event_platform
REDIS_URL=redis://localhost:6379/0
JWT_SECRET_KEY=replace-with-a-long-random-secret
OTP_HASH_PEPPER=replace-with-a-random-secret
IDENTITY_DOC_ENCRYPTION_KEY=
TICKET_QR_SECRET=replace-with-a-random-secret
```

Generate an identity-document key when identity document storage is enabled:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

For real Razorpay integration, configure `PAYMENT_GATEWAY_KEY_ID`, `PAYMENT_GATEWAY_KEY_SECRET`, `PAYMENT_GATEWAY_API_URL`, and `PAYMENT_GATEWAY_WEBHOOK_SECRET`. For real OTP delivery, configure the SMS provider variables in `.env`.

## Local Dependencies with Docker

The compose file exposes PostgreSQL on host port `5433`, Redis on `6379`, and MinIO on `9000`/`9001`:

```bash
docker compose -f docker/docker-compose.yml up -d postgres redis minio
```

When running Uvicorn on the host, use:

```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/event_platform
REDIS_URL=redis://localhost:6379/0
MINIO_ENDPOINT=localhost:9000
```

To run the complete backend stack in Docker, the backend container must use service names rather than `localhost`:

```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/event_platform
REDIS_URL=redis://redis:6379/0
MINIO_ENDPOINT=minio:9000
```

Then run:

```bash
docker compose -f docker/docker-compose.yml up --build
```

The API is available at `http://localhost:8001`; OpenAPI documentation is at `http://localhost:8001/docs`.

## Database Migrations

Always run migrations before starting clients:

```bash
source venv/bin/activate
alembic upgrade head
alembic current
```

The migration head creates and updates all registered module tables, including event configuration, feedback, sponsorships, volunteer applications, payment/refund state, tickets, and check-ins. Do not use `Base.metadata.create_all()` as a replacement for Alembic in a shared or production database.

## Run the API on the Host

```bash
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

The versioned API prefix is `/api/v1`. OpenAPI documentation is available at `/docs` and `/redoc`.

## Background Worker

Notification delivery and other asynchronous jobs use Celery with Redis:

```bash
source venv/bin/activate
celery -A app.core.background_jobs.celery_app worker --loglevel=info
```

Run the worker against the same `.env` and Redis instance as the API.

## API and Authorization Model

- Public/read-only event, category, schedule, venue, sponsor, media, and competition content may be accessed without a user token where the route permits it.
- Registration, feedback writes, payments, tickets, user data, team/guardian actions, and personalized data require a valid access token.
- Operations/Super Admin roles can access global operations data.
- Event Managers can access only active assigned event IDs. Server-side scope checks apply when `event_id` is omitted, supplied as a query parameter, embedded in a request body, or inferred from a direct registration/ticket/check-in/report ID.
- Finance/payment/refund endpoints require global finance authorization.
- `/registrations/mine`, `/tickets/mine`, `/feedback/mine`, and similar self-service routes are owner-scoped.
- The backend, not the console or mobile app, is the authorization boundary.

## Core Lifecycle

1. Console creates/configures an event and its category, subcategory, capacity, deadline, participation types, and fee.
2. Backend persists the event and configuration in PostgreSQL.
3. Mobile reads the event and configuration from the backend; guest users can browse public content.
4. An authenticated user creates a self, child, other-participant, or team registration.
5. Backend validates ownership, event scope, eligibility, capacity, deadline, duplicates, and concurrency.
6. Paid registrations create Razorpay orders. Payment signatures and webhooks are verified server-side and handled idempotently.
7. Confirmed registrations receive unique signed QR tickets. Free registrations receive tickets without a payment step.
8. Authorized event staff resolve and validate the signed QR payload and check in the ticket once.
9. Full refunds cancel the issued ticket; invalid, unpaid, cancelled, tampered, or already-used tickets are rejected.

## Testing and Static Checks

```bash
source venv/bin/activate
pytest -q
python -m compileall -q app
alembic current
git diff --check
```

The test suite covers event configuration, registration rules, capacity/deadline behavior, authorization scope, payment verification, refunds, tickets/check-ins, feedback, sponsorships, and volunteer applications. Live Razorpay, SMS, storage, and device scanning require external credentials/services and are not covered by unit tests.

## Production Checklist

- Use strong unique JWT, OTP, QR, encryption, and webhook secrets.
- Use managed PostgreSQL, Redis, and object storage with backups and TLS.
- Run `alembic upgrade head` as a controlled deployment step.
- Configure a real Razorpay webhook URL and secret; verify HTTPS and replay/idempotency behavior.
- Configure an actual SMS provider and never expose OTPs in production logs.
- Configure CORS only for the deployed console/mobile origins.
- Run the API and Celery worker as separate supervised processes.
- Monitor failed payments, webhook failures, registration capacity errors, check-in conflicts, and background job retries.

## Screenshot-based GO-360° dummy data

The seed owns the screenshot's four main categories, topic sub-categories, 16 events and connected operational fixtures in the backend. Existing equivalent taxonomy is reused. Reset is dummy-only and preserves unrelated rows; it no longer truncates application tables.

```bash
cd /Users/dishajain/Desktop/event-platform-backend
venv/bin/alembic upgrade head
# Fresh/reset seed:
venv/bin/python -m scripts.seed_platform reset --size medium
# Refresh dummy fixtures:
venv/bin/python -m scripts.seed_platform refresh --size medium
# Add missing dummy rows, preserving existing data:
venv/bin/python -m scripts.seed_platform add --size medium
# Counts, hierarchy, references and both client API response formats:
venv/bin/python -m scripts.validate_seed
venv/bin/python -m scripts.verify_seed_api
```

See [seed instructions, counts, safety guarantees and screenshot assumptions](scripts/seed/README.md). Run commands with the intended local `.env`, PostgreSQL and Redis available. No frontend hardcoded dataset is used.

## Account Disable / Reactivate

Account status uses the existing persisted `users.is_active` value as its single source of truth. Identity responses expose `status: "ACTIVE" | "DISABLED"` and retain `is_active` for compatibility. No new status table or migration is needed.

`PATCH /api/v1/users/{user_id}/status` accepts `{"status":"DISABLED"}` or `{"status":"ACTIVE"}`. The legacy `{"is_active":false}` form remains supported; contradictory values are rejected. `GET /api/v1/users/accounts` returns the caller's permitted account list and a server-computed `can_manage_status` flag.

| Actor | May disable/reactivate |
|---|---|
| Super Admin | Any other account |
| Operations Admin | Event Managers only, including eligible unassigned managers |
| Finance Admin | Finance Operators and Finance Auditors only |
| Event Manager | Approved volunteer accounts within their active managed events |

Self-status changes are denied. Non-super admins cannot act on targets with additional higher/unrelated roles. Managers cannot disable shared volunteers with active assignments/applications outside their controlled events, or with registrations in another organization. Existing global admin roles remain platform-wide: the current schema has event organizations but no tenant-specific admin membership model. This feature uses those existing global/event scopes, rather than inventing a separate tenant permission system.

The Console exposes confirmed Disable/Reactivate actions in Admin Accounts (Finance Accounts for Finance Admin). Mobile Event Managers can use Staff Profile → Volunteer accounts. Both clients use backend eligibility and display Active/Disabled indicators and server errors.

Disabled accounts cannot request/verify OTPs, complete email verification, log in by password, refresh tokens, or call protected APIs with earlier-issued tokens. Password recovery cannot reactivate an account. The account-disabled error ends client sessions without token refresh; live invalidation and foreground reconnection also refresh permissions. Guest browsing remains public. Reactivation preserves the account, roles and history. Normal clients must sign in again after their disabled session has been cleared.

Changes produce `account_disabled`/`account_reactivated` audit entries with actor, target, and before/after state. Requests lock actor/target records in stable order and repeated requests for the existing status are idempotent.

```bash
venv/bin/python -m pytest tests/test_account_status.py -q
```
