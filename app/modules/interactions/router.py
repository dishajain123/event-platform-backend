import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import Page
from app.core.permissions import user_has_global_role, user_has_scoped_role, user_scoped_event_ids
from app.database import get_db
from app.dependencies import get_current_user, get_current_user_optional
from app.exceptions import PermissionDeniedError
from app.modules.identity.models import User
from app.modules.interactions.models import PollStatus, QuestionStatus
from app.modules.interactions.schemas import InteractionMetricsOut, PollCreateIn, PollOut, PollResultOut, PollStatusIn, QuestionAnswerIn, QuestionCreateIn, QuestionModerateIn, QuestionOut, VoteIn, VoteOut
from app.modules.interactions.service import InteractionService
from app.modules.rbac.models import RoleName

router = APIRouter(prefix="/interactions", tags=["event-interactions"])
GLOBAL = {RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN}
MANAGERS = {RoleName.EVENT_MANAGER, RoleName.EVENT_COORDINATOR}


def service(db: AsyncSession = Depends(get_db)) -> InteractionService:
    return InteractionService(db)


async def can_manage(db, user, event_id):
    return await user_has_global_role(db, user.id, GLOBAL) or await user_has_scoped_role(db, user.id, MANAGERS, event_id, allow_global_roles=GLOBAL)


async def event_scope(db, user, event_id):
    if await user_has_global_role(db, user.id, GLOBAL):
        return event_id
    ids = await user_scoped_event_ids(db, user.id, MANAGERS)
    if event_id is not None and event_id not in ids:
        raise PermissionDeniedError("You don't have permission for this event.")
    return event_id if event_id is not None else next(iter(ids), None)


@router.get("/events/{event_id}/polls", response_model=Page[PollOut])
async def list_polls(event_id: uuid.UUID, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100), current_user: User | None = Depends(get_current_user_optional), db: AsyncSession = Depends(get_db), svc: InteractionService = Depends(service)):
    public = current_user is None or not await can_manage(db, current_user, event_id)
    return await svc.list_polls(event_id, page, page_size, public=public)


@router.post("/events/{event_id}/polls", response_model=PollOut, status_code=status.HTTP_201_CREATED)
async def create_poll(event_id: uuid.UUID, payload: PollCreateIn, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), svc: InteractionService = Depends(service)):
    if not await can_manage(db, current_user, event_id): raise PermissionDeniedError("Not authorized for this event.")
    return await svc.create_poll(event_id, current_user, payload)


@router.post("/polls/{poll_id}/status", response_model=PollOut)
async def change_poll_status(poll_id: uuid.UUID, payload: PollStatusIn, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), svc: InteractionService = Depends(service)):
    poll = await svc.poll(poll_id)
    if not await can_manage(db, current_user, poll.event_id): raise PermissionDeniedError("Not authorized for this event.")
    return await svc.change_poll_status(poll_id, current_user, payload.status)


@router.get("/polls/{poll_id}", response_model=PollOut)
async def get_poll(poll_id: uuid.UUID, current_user: User | None = Depends(get_current_user_optional), db: AsyncSession = Depends(get_db), svc: InteractionService = Depends(service)):
    poll = await svc.poll(poll_id)
    if current_user is None or not await can_manage(db, current_user, poll.event_id):
        if poll.status not in {PollStatus.SCHEDULED, PollStatus.LIVE, PollStatus.CLOSED}: raise PermissionDeniedError("Poll is not public.")
    return await svc.poll_out(poll)


@router.post("/polls/{poll_id}/vote", response_model=VoteOut)
async def vote(poll_id: uuid.UUID, payload: VoteIn, current_user: User = Depends(get_current_user), svc: InteractionService = Depends(service)):
    response, option_ids = await svc.vote(poll_id, current_user, payload.option_ids)
    return VoteOut(poll_id=poll_id, option_ids=option_ids, submitted_at=response.submitted_at)


@router.get("/polls/{poll_id}/vote", response_model=VoteOut | None)
async def my_vote(poll_id: uuid.UUID, current_user: User = Depends(get_current_user), svc: InteractionService = Depends(service)):
    result = await svc.vote_for(poll_id, current_user.id)
    return VoteOut(poll_id=poll_id, option_ids=result[0], submitted_at=result[1]) if result else None


@router.get("/polls/{poll_id}/results", response_model=list[PollResultOut])
async def results(poll_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), svc: InteractionService = Depends(service)):
    poll = await svc.poll(poll_id)
    manager = await can_manage(db, current_user, poll.event_id)
    return await svc.results(poll_id, current_user, manager=manager)


@router.post("/events/{event_id}/questions", response_model=QuestionOut, status_code=status.HTTP_201_CREATED)
async def submit_question(event_id: uuid.UUID, payload: QuestionCreateIn, current_user: User = Depends(get_current_user), svc: InteractionService = Depends(service)):
    return await svc.submit_question(event_id, current_user, payload)


@router.get("/events/{event_id}/questions", response_model=Page[QuestionOut])
async def public_questions(event_id: uuid.UUID, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100), current_user: User | None = Depends(get_current_user_optional), svc: InteractionService = Depends(service)):
    return await svc.questions(event_id, page, page_size, public=True, user_id=current_user.id if current_user else None)


@router.get("/events/{event_id}/questions/manage", response_model=Page[QuestionOut])
async def manage_questions(event_id: uuid.UUID, status_filter: QuestionStatus | None = Query(None, alias="status"), search: str | None = Query(None, max_length=100), page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), svc: InteractionService = Depends(service)):
    if not await can_manage(db, current_user, event_id): raise PermissionDeniedError("Not authorized for this event.")
    return await svc.questions(event_id, page, page_size, status=status_filter, search=search, user_id=current_user.id)


@router.post("/questions/{question_id}/moderate", response_model=QuestionOut)
async def moderate(question_id: uuid.UUID, payload: QuestionModerateIn, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), svc: InteractionService = Depends(service)):
    question = await svc.question(question_id)
    if not await can_manage(db, current_user, question.event_id): raise PermissionDeniedError("Not authorized for this event.")
    return await svc.moderate(question_id, current_user, payload.status)


@router.post("/questions/{question_id}/answer", response_model=QuestionOut)
async def answer(question_id: uuid.UUID, payload: QuestionAnswerIn, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), svc: InteractionService = Depends(service)):
    question = await svc.question(question_id)
    if not await can_manage(db, current_user, question.event_id): raise PermissionDeniedError("Not authorized for this event.")
    return await svc.answer(question_id, current_user, payload.answer_text)


@router.post("/questions/{question_id}/upvote")
async def upvote(question_id: uuid.UUID, current_user: User = Depends(get_current_user), svc: InteractionService = Depends(service)):
    return await svc.upvote(question_id, current_user)


@router.get("/events/{event_id}/metrics", response_model=InteractionMetricsOut)
async def metrics(event_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), svc: InteractionService = Depends(service)):
    if not await can_manage(db, current_user, event_id): raise PermissionDeniedError("Not authorized for this event.")
    return await svc.metrics(event_id)
