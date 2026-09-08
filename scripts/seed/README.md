# Local Demo Data

The backend is the only source of demo data. The Flutter app and Operations Console consume these records through their normal API clients; no frontend mock dataset is maintained.

## Commands

From `/Users/dishajain/Desktop/event-platform-backend`:

```bash
source venv/bin/activate
alembic upgrade head
python -m scripts.seed_platform seed --size small
python -m scripts.validate_seed
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
pytest -q
```

Use `medium` for normal pagination/search work and `large` for a heavier local dataset:

```bash
python -m scripts.seed_platform seed --size medium
python -m scripts.seed_platform seed --size large
```

Seeding is deterministic and idempotent for the `DEMO-` records. The explicit reset command is destructive and is refused unless `ENVIRONMENT` is `development`, `test`, or `local`:

```bash
python -m scripts.seed_platform reset
```

## Generated coverage

The seed creates roles, granular permissions and scoped assignments; users and verified identity documents; categories/subcategories; events, templates, configuration, field schemas, venues and schedules; registrations/participants and guardian relationships; teams, members, invitations and join requests; staff assignment history; access policies/zones, Code 128-compatible tickets, transfers and check-ins; payments, refunds, discount codes and processed webhook inbox records; volunteer applications/shifts/attendance; feedback, incidents, audit logs, media/highlights; notifications/preferences/templates/device tokens; sponsorship inquiries/packages/deliverables/engagements; competitions/stages/entries/matches/stage decisions; networking profiles/connections/dismissals/reports; polls, responses, votes, questions and upvotes; certificates/badges; waitlists, assistance requests, referrals and rewards.

The small/medium/large profiles create 8/24/72 participants plus fixed operational accounts and three events. Dates cover completed, published/future, and currently open events. Statuses intentionally cover confirmed, checked-in, completed, approved, pending payment, and cancelled registrations.

## Local accounts

The generated accounts use mobile numbers `+919800000001` onward and emails ending in `@event-platform.test`. OTP login remains the real authentication path; the seed never stores passwords or production credentials. The first fixed accounts are Super Admin, Operations Admin, Finance Admin, Event Manager, Staff Member, and Volunteer in that order.

## Validation and limitations

`validate_seed.py` checks demo roots, stable IDs, registration ownership, and queryability of every event-scoped table. API smoke tests should be run against a started backend because authentication tokens and external providers are runtime concerns. Razorpay, SMS, push delivery, object storage, physical barcode scanning, and device offline transitions require their real local/test services and are not fabricated by this seed.
