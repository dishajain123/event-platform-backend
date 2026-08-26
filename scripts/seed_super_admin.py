"""
Run once, at deployment time, to seed the built-in roles and create the
first Super Admin account. Every other account in the platform is
created afterward through the normal API (Super Admin creates
Operations Admin / Finance Admin; Operations Admin creates every
field-role account) — this script is the one manual bootstrap step.

Usage:
    python -m scripts.seed_super_admin --mobile +919999999999
"""
import argparse
import asyncio

from app.core import model_registry  # noqa: F401
from app.database import AsyncSessionLocal
from app.modules.identity.models import User
from app.modules.rbac.models import GLOBAL_ROLES, SCOPED_ROLES, Role, RoleAssignment, RoleName


async def seed_roles(db) -> None:
    from sqlalchemy import select

    existing = (await db.execute(select(Role.name))).scalars().all()
    existing_names = set(existing)

    for role_name in RoleName:
        if role_name in existing_names:
            continue
        db.add(
            Role(
                name=role_name,
                is_scoped=role_name in SCOPED_ROLES,
                description=None,
            )
        )
    await db.commit()


async def seed_super_admin(db, mobile_number: str) -> None:
    from sqlalchemy import select

    result = await db.execute(select(User).where(User.mobile_number == mobile_number))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(mobile_number=mobile_number)
        db.add(user)
        await db.flush()

    role_result = await db.execute(select(Role).where(Role.name == RoleName.SUPER_ADMIN))
    super_admin_role = role_result.scalar_one()

    existing_assignment = await db.execute(
        select(RoleAssignment).where(
            RoleAssignment.user_id == user.id, RoleAssignment.role_id == super_admin_role.id
        )
    )
    if existing_assignment.scalar_one_or_none() is None:
        db.add(RoleAssignment(user_id=user.id, role_id=super_admin_role.id, event_id=None))

    await db.commit()
    print(f"Super Admin ready: mobile_number={mobile_number}, user_id={user.id}")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mobile", required=True, help="Mobile number for the Super Admin account")
    args = parser.parse_args()

    async with AsyncSessionLocal() as db:
        await seed_roles(db)
        await seed_super_admin(db, args.mobile)


if __name__ == "__main__":
    asyncio.run(main())