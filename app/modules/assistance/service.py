"""Assistance request routing and decision logic."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.core.permissions import user_has_global_role, user_has_scoped_role
from app.exceptions import PermissionDeniedError
from app.modules.assistance.exceptions import (
    AssistanceConflictError,
    AssistanceRequestNotFoundError,
    AssistanceReviewerNotFoundError,
    InvalidAssistanceStateError,
)
from app.modules.assistance.models import AssistanceRequest, AssistanceRequestStatus
from app.modules.assistance.repository import AssistanceRepository
from app.modules.identity.models import User
from app.modules.payments.models import DiscountType
from app.modules.payments.repository import DiscountCodeRepository, PaymentRepository
from app.modules.rbac.models import RoleName
from app.modules.registrations.models import RegistrationStatus
from app.modules.registrations.repository import RegistrationRepository
from app.modules.staff.models import StaffAssignmentStatus
from app.modules.staff.repository import StaffAssignmentRepository


class AssistanceService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.requests = AssistanceRepository(db)
        self.registrations = RegistrationRepository(db)
        self.payments = PaymentRepository(db)
        self.staff_assignments = StaffAssignmentRepository(db)
        self.discount_codes = DiscountCodeRepository(db)

    async def _can_review_event(self, actor: User, event_id: uuid.UUID) -> bool:
        return await user_has_scoped_role(
            self.db,
            actor.id,
            {RoleName.EVENT_MANAGER, RoleName.EVENT_COORDINATOR, RoleName.STAFF_LEAD, RoleName.STAFF_MEMBER},
            event_id,
            allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN},
        )

    async def _get_reviewers_for_event(self, event_id: uuid.UUID) -> list[uuid.UUID]:
        assignments = await self.staff_assignments.list_for_event(event_id)
        preferred = []
        fallback = []
        for assignment in assignments:
            if assignment.status != StaffAssignmentStatus.ACTIVE or assignment.user_id is None:
                continue
            if assignment.role_label.lower() in {"reviewer", "assistance_reviewer", "event_manager", "event_coordinator"}:
                preferred.append(assignment.user_id)
            else:
                fallback.append(assignment.user_id)
        return preferred or fallback

    async def create_request(
        self,
        *,
        event_id: uuid.UUID,
        actor: User,
        registration_id: uuid.UUID,
        reason: str,
        requested_fee_waiver_amount: Decimal | None = None,
    ) -> AssistanceRequest:
        registration = await self.registrations.get_by_id(registration_id)
        if registration is None or registration.event_id != event_id:
            raise InvalidAssistanceStateError("Registration not found for this event.")
        if registration.user_id != actor.id:
            raise PermissionDeniedError("You can only request assistance for your own registration.")

        existing = await self.requests.get_by_registration_id(registration_id)
        if existing is not None:
            raise AssistanceConflictError("An assistance request already exists for this registration.")

        reviewer_ids = await self._get_reviewers_for_event(event_id)
        if not reviewer_ids:
            raise AssistanceReviewerNotFoundError("No reviewer is assigned to this event.")

        request = await self.requests.create(
            event_id=event_id,
            registration_id=registration_id,
            requester_user_id=actor.id,
            reviewer_user_id=reviewer_ids[0],
            status=AssistanceRequestStatus.ASSIGNED,
            reason=reason,
            requested_fee_waiver_amount=requested_fee_waiver_amount,
        )
        await write_audit_log(
            self.db,
            entity_type="assistance_request",
            entity_id=request.id,
            action="created",
            actor_user_id=actor.id,
            after_value={"reviewer_user_id": str(request.reviewer_user_id)},
        )
        await self.db.commit()
        await self.db.refresh(request)
        return request

    async def list_requests(self, *, event_id: uuid.UUID, actor: User) -> list[AssistanceRequest]:
        if not await self._can_review_event(actor, event_id):
            raise PermissionDeniedError("You don't have permission to view assistance requests for this event.")
        return await self.requests.list_for_event(event_id)

    async def decide_request(
        self,
        request_id: uuid.UUID,
        actor: User,
        *,
        approve: bool,
        decision_reason: str | None = None,
        requested_fee_waiver_amount: Decimal | None = None,
    ) -> AssistanceRequest:
        request = await self.requests.get_by_id(request_id)
        if request is None:
            raise AssistanceRequestNotFoundError("Assistance request not found.")
        if not await self._can_review_event(actor, request.event_id):
            raise PermissionDeniedError("You don't have permission to decide this request.")
        if request.status not in {AssistanceRequestStatus.ASSIGNED, AssistanceRequestStatus.PENDING}:
            raise InvalidAssistanceStateError("This request has already been decided.")

        request.decision_reason = decision_reason
        request.decided_by = actor.id
        request.decided_at = datetime.now(timezone.utc)

        if approve:
            waiver = requested_fee_waiver_amount or request.requested_fee_waiver_amount or Decimal("0")
            if waiver < 0:
                raise InvalidAssistanceStateError("Fee waiver amount cannot be negative.")
            if waiver > 0:
                discount_code = f"WAIVE-{request.id.hex[:8].upper()}"
                await self.discount_codes.create(
                    event_id=request.event_id,
                    code=discount_code,
                    discount_type=DiscountType.FIXED,
                    value=int(waiver),
                    is_active=True,
                    max_redemptions=1,
                    discount_metadata={"assistance_request_id": str(request.id)},
                )
                request.applied_discount_code = discount_code
            request.status = AssistanceRequestStatus.APPROVED
            action = "approved"
        else:
            request.status = AssistanceRequestStatus.REJECTED
            action = "rejected"

        await write_audit_log(
            self.db,
            entity_type="assistance_request",
            entity_id=request.id,
            action=action,
            actor_user_id=actor.id,
            after_value={
                "status": request.status.value,
                "applied_discount_code": request.applied_discount_code,
            },
        )
        await self.db.commit()
        await self.db.refresh(request)
        return request
