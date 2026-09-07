import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.models import User
from app.modules.incidents.models import Incident, IncidentSeverity, IncidentStatus
from app.modules.rbac.models import AssignmentStatus, Role, RoleAssignment, RoleName


class IncidentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **fields) -> Incident:
        incident = Incident(**fields)
        self.db.add(incident)
        await self.db.flush()
        return incident

    async def get(self, incident_id: uuid.UUID) -> Incident | None:
        return await self.db.get(Incident, incident_id)

    async def page(self, *, event_ids: set[uuid.UUID] | None, event_id=None, status=None,
                   severity=None, category=None, assigned_user_id=None, search=None,
                   page=1, page_size=25):
        filters = []
        if event_ids is not None:
            if not event_ids:
                return [], 0
            filters.append(Incident.event_id.in_(event_ids))
        if event_id is not None:
            filters.append(Incident.event_id == event_id)
        if status is not None:
            filters.append(Incident.status == status)
        if severity is not None:
            filters.append(Incident.severity == severity)
        if category:
            filters.append(Incident.category == category)
        if assigned_user_id is not None:
            filters.append(Incident.assigned_user_id == assigned_user_id)
        if search:
            term = f"%{search.strip()}%"
            filters.append(or_(Incident.title.ilike(term), Incident.description.ilike(term)))
        total = int(await self.db.scalar(select(func.count(Incident.id)).where(*filters)) or 0)
        result = await self.db.execute(
            select(Incident).where(*filters)
            .order_by(Incident.created_at.desc(), Incident.id.desc())
            .offset((page - 1) * page_size).limit(page_size)
        )
        return list(result.scalars().all()), total

    async def operational_recipient_ids(self, event_id: uuid.UUID) -> set[uuid.UUID]:
        result = await self.db.execute(
            select(RoleAssignment.user_id)
            .join(Role, RoleAssignment.role_id == Role.id)
            .where(
                RoleAssignment.status == AssignmentStatus.ACTIVE,
                Role.name.in_({RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN}),
                RoleAssignment.event_id.is_(None),
            )
            .union(
                select(RoleAssignment.user_id)
                .join(Role, RoleAssignment.role_id == Role.id)
                .where(
                    RoleAssignment.status == AssignmentStatus.ACTIVE,
                    Role.name == RoleName.EVENT_MANAGER,
                    RoleAssignment.event_id == event_id,
                )
            )
        )
        return {row[0] for row in result.all()}
