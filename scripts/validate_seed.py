"""Validate the canonical DEMO- dataset without mutating application data."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import sys
from pathlib import Path

from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core import model_registry  # noqa: F401
from app.core.base_model import Base
from app.database import AsyncSessionLocal
from app.modules.events.models import Event
from app.modules.identity.models import User
from app.modules.organizations.models import Organization
from app.modules.registrations.models import Registration
from app.modules.tickets.models import Ticket
from app.config import get_settings
from scripts.seed_platform import SEED_PREFIX


async def validate() -> int:
    checks: list[tuple[str, bool, str]] = []
    async with AsyncSessionLocal() as db:
        demo_events = list((await db.execute(select(Event).where(Event.name.like(f"{SEED_PREFIX}%")))).scalars())
        demo_users = list((await db.execute(select(User).where(User.email.like("%@event-platform.test")))).scalars())
        demo_orgs = list((await db.execute(select(Organization).where(Organization.name.like(f"{SEED_PREFIX}%")))).scalars())
        checks.append(("seed roots", bool(demo_events and demo_users and demo_orgs), f"events={len(demo_events)}, users={len(demo_users)}"))
        checks.append(("stable event identifiers", len({event.id for event in demo_events}) == len(demo_events), "no duplicate event IDs"))
        registrations = list((await db.execute(select(Registration).where(Registration.event_id.in_([event.id for event in demo_events])))).scalars()) if demo_events else []
        checks.append(("registration references", all(reg.event_id in {event.id for event in demo_events} and reg.user_id in {user.id for user in demo_users} for reg in registrations), f"registrations={len(registrations)}"))
        tickets = list((await db.execute(select(Ticket).where(Ticket.event_id.in_([event.id for event in demo_events])))).scalars()) if demo_events else []
        secret = get_settings().ticket_barcode_secret.encode()
        signatures_valid = all(
            hmac.compare_digest(
                hmac.new(secret, ticket.barcode_payload.encode(), hashlib.sha256).hexdigest(),
                ticket.barcode_signature,
            )
            for ticket in tickets
        )
        checks.append(("ticket barcode signatures", signatures_valid, f"tickets={len(tickets)}"))
        # Every mapped table with event_id must contain no orphan references
        # inside the seeded dataset. This uses NOT EXISTS against the actual
        # foreign-key target, rather than treating a successful SELECT as
        # proof of referential integrity.
        event_ids = {event.id for event in demo_events}
        for table in Base.metadata.tables.values():
            if "event_id" not in table.c:
                continue
            result = await db.execute(select(func.count()).select_from(table).where(table.c.event_id.in_(event_ids)))
            checks.append((f"{table.name} queryable", int(result.scalar_one()) >= 0, "query completed"))
            for constraint in table.foreign_key_constraints:
                local_column = next(iter(constraint.columns))
                remote_column = next(iter(constraint.elements)).column
                orphan_count = await db.scalar(
                    select(func.count())
                    .select_from(table)
                    .where(
                        table.c.event_id.in_(event_ids),
                        local_column.is_not(None),
                        ~remote_column.table.select().where(remote_column == local_column).exists(),
                    )
                )
                checks.append((f"{table.name}.{local_column.name} references", int(orphan_count or 0) == 0, f"orphans={int(orphan_count or 0)}"))
    failed = [item for item in checks if not item[1]]
    print("Seed Validation\n===============")
    for name, passed, detail in checks:
        print(f"{name}: {'PASS' if passed else 'FAIL'} ({detail})")
    print(f"\nTotal checks: {len(checks)}\nPassed: {len(checks) - len(failed)}\nFailed: {len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(validate()))
