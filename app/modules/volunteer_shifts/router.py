import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import Page
from app.database import get_db
from app.dependencies import get_current_user
from app.modules.identity.models import User
from app.modules.volunteer_shifts.models import VolunteerAssignmentStatus, VolunteerShiftStatus
from app.modules.volunteer_shifts.schemas import AssignmentDetailOut, AssignmentOut, AssignmentStatusIn, AttendanceOut, EligibleVolunteerOut, ShiftCreateIn, ShiftOut, ShiftUpdateIn
from app.modules.volunteer_shifts.service import VolunteerShiftService

router = APIRouter(prefix="/volunteer-shifts", tags=["volunteer-shifts"])


def get_service(db: AsyncSession = Depends(get_db)) -> VolunteerShiftService:
    return VolunteerShiftService(db)


@router.get("", response_model=Page[ShiftOut])
async def list_shifts(
    event_id: uuid.UUID | None = None,
    search: str | None = None,
    shift_status: VolunteerShiftStatus | None = Query(None, alias="status"),
    page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
    current_user: User = Depends(get_current_user), service: VolunteerShiftService = Depends(get_service),
):
    items, total = await service.list_shifts(current_user, event_id=event_id, page=page, page_size=page_size, search=search, status=shift_status)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.post("", response_model=ShiftOut, status_code=status.HTTP_201_CREATED)
async def create_shift(event_id: uuid.UUID, payload: ShiftCreateIn, current_user: User = Depends(get_current_user), service: VolunteerShiftService = Depends(get_service)):
    return await service.create_shift(current_user, event_id, payload)


@router.get("/available", response_model=Page[ShiftOut])
async def list_available_shifts(
    search: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
    current_user: User = Depends(get_current_user), service: VolunteerShiftService = Depends(get_service),
):
    items, total = await service.list_available(page=page, page_size=page_size, search=search)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/assignments/mine", response_model=Page[AssignmentOut])
async def my_assignments(
    page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
    assignment_status: VolunteerAssignmentStatus | None = Query(None, alias="status"),
    current_user: User = Depends(get_current_user), service: VolunteerShiftService = Depends(get_service),
):
    items, total = await service.list_assignments(current_user, user_id=current_user.id, page=page, page_size=page_size, status=assignment_status)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/{shift_id}", response_model=ShiftOut)
async def get_shift(shift_id: uuid.UUID, current_user: User = Depends(get_current_user), service: VolunteerShiftService = Depends(get_service)):
    return await service.get_visible_shift(current_user, shift_id)


@router.patch("/{shift_id}", response_model=ShiftOut)
async def update_shift(shift_id: uuid.UUID, payload: ShiftUpdateIn, current_user: User = Depends(get_current_user), service: VolunteerShiftService = Depends(get_service)):
    return await service.update_shift(current_user, shift_id, payload)


@router.post("/{shift_id}/request", response_model=AssignmentOut, status_code=status.HTTP_201_CREATED)
async def request_shift(shift_id: uuid.UUID, current_user: User = Depends(get_current_user), service: VolunteerShiftService = Depends(get_service)):
    return await service.request_shift(current_user, shift_id)


@router.post("/{shift_id}/assign/{user_id}", response_model=AssignmentOut, status_code=status.HTTP_201_CREATED)
async def assign_shift(shift_id: uuid.UUID, user_id: uuid.UUID, current_user: User = Depends(get_current_user), service: VolunteerShiftService = Depends(get_service)):
    return await service.assign_shift(current_user, shift_id, user_id)


@router.get("/{shift_id}/eligible-volunteers", response_model=Page[EligibleVolunteerOut])
async def eligible_volunteers(
    shift_id: uuid.UUID, search: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
    current_user: User = Depends(get_current_user), service: VolunteerShiftService = Depends(get_service),
):
    items, total = await service.eligible_volunteers(current_user, shift_id, page=page, page_size=page_size, search=search)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/{shift_id}/assignments", response_model=Page[AssignmentOut])
async def list_shift_assignments(
    shift_id: uuid.UUID, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
    search: str | None = None, assignment_status: VolunteerAssignmentStatus | None = Query(None, alias="status"),
    current_user: User = Depends(get_current_user), service: VolunteerShiftService = Depends(get_service),
):
    items, total = await service.list_assignments(current_user, shift_id=shift_id, page=page, page_size=page_size, status=assignment_status, search=search)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.patch("/assignments/{assignment_id}/status", response_model=AssignmentOut)
async def update_assignment(assignment_id: uuid.UUID, payload: AssignmentStatusIn, current_user: User = Depends(get_current_user), service: VolunteerShiftService = Depends(get_service)):
    return await service.update_assignment(current_user, assignment_id, payload.status)


@router.get("/assignments/{assignment_id}", response_model=AssignmentDetailOut)
async def get_assignment(assignment_id: uuid.UUID, current_user: User = Depends(get_current_user), service: VolunteerShiftService = Depends(get_service)):
    return await service.get_assignment_visible(current_user, assignment_id)


@router.post("/assignments/{assignment_id}/check-in", response_model=AttendanceOut)
async def check_in(assignment_id: uuid.UUID, current_user: User = Depends(get_current_user), service: VolunteerShiftService = Depends(get_service)):
    return await service.check_in(current_user, assignment_id)


@router.post("/assignments/{assignment_id}/check-out", response_model=AttendanceOut)
async def check_out(assignment_id: uuid.UUID, current_user: User = Depends(get_current_user), service: VolunteerShiftService = Depends(get_service)):
    return await service.check_out(current_user, assignment_id)


@router.get("/assignments/{assignment_id}/attendance", response_model=AttendanceOut | None)
async def get_attendance(assignment_id: uuid.UUID, current_user: User = Depends(get_current_user), service: VolunteerShiftService = Depends(get_service)):
    return await service.get_attendance(current_user, assignment_id)


@router.post("/assignments/{assignment_id}/no-show", response_model=AttendanceOut)
async def mark_no_show(assignment_id: uuid.UUID, current_user: User = Depends(get_current_user), service: VolunteerShiftService = Depends(get_service)):
    return await service.mark_no_show(current_user, assignment_id)
