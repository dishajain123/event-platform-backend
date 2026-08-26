"""Minimal CRUD, Super Admin only — see module docstring in models.py."""
from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_role
from app.modules.organizations.models import Organization
from app.modules.organizations.schemas import OrganizationIn, OrganizationOut
from app.modules.rbac.models import RoleName

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.post(
    "",
    response_model=OrganizationOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(RoleName.SUPER_ADMIN))],
)
async def create_organization(payload: OrganizationIn, db: AsyncSession = Depends(get_db)):
    """Called by: console (Super Admin only)."""
    org = Organization(name=payload.name, contact_email=payload.contact_email)
    db.add(org)
    await db.commit()
    await db.refresh(org)
    return org


@router.get(
    "",
    response_model=list[OrganizationOut],
    dependencies=[Depends(require_role(RoleName.SUPER_ADMIN))],
)
async def list_organizations(db: AsyncSession = Depends(get_db)):
    """Called by: console (Super Admin only)."""
    result = await db.execute(select(Organization))
    return list(result.scalars().all())