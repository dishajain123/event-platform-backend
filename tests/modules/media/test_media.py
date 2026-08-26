"""
Phase 7 media coverage.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.modules.events.service import EventService
from app.modules.identity.models import User
from app.modules.media.models import MediaType
from app.modules.media.schemas import MediaPublishIn, MediaUploadIn
from app.modules.media.service import MediaService
from app.modules.rbac.models import Role, RoleAssignment, RoleName


async def _assign_role(db_session, user: User, role_name: RoleName, event_id=None):
    role = (await db_session.execute(select(Role).where(Role.name == role_name))).scalar_one()
    db_session.add(RoleAssignment(user_id=user.id, role_id=role.id, event_id=event_id))
    await db_session.flush()


async def _make_event(db_session):
    creator = User(mobile_number="+919600000001")
    manager = User(mobile_number="+919600000002")
    admin = User(mobile_number="+919600000003")
    db_session.add_all([creator, manager, admin])
    await db_session.flush()

    start = datetime.now(timezone.utc) + timedelta(days=5)
    event = await EventService(db_session).create_event(
        created_by=creator.id,
        name="Phase 7 Media Event",
        description="fixture",
        category="sample",
        start_date=start,
        end_date=start + timedelta(days=1),
        organization_id=None,
    )

    await _assign_role(db_session, manager, RoleName.EVENT_MANAGER, event.id)
    await _assign_role(db_session, admin, RoleName.SUPER_ADMIN)

    return event, manager, admin


@pytest.mark.asyncio
async def test_upload_publish_and_unpublish_controls_public_visibility(db_session):
    event, manager, admin = await _make_event(db_session)
    service = MediaService(db_session)

    media = await service.upload_media(
        event.id,
        manager,
        MediaUploadIn(
            title="Opening Ceremony",
            caption="First official photo",
            category="ceremony",
            media_type=MediaType.IMAGE,
            source_url=None,
            sort_order=1,
            is_highlight=True,
            highlight_title="Opening highlight",
            highlight_description="The ceremony opening shot",
            highlight_order=0,
        ),
    )

    assert media.is_published is False

    public_before = await service.list_event_media(event.id)
    assert public_before == []

    published = await service.publish_media(media.id, admin, is_published=True)
    assert published.is_published is True

    public_after = await service.list_event_media(event.id)
    assert len(public_after) == 1
    assert public_after[0].title == "Opening Ceremony"
    assert public_after[0].highlight is not None
    assert public_after[0].highlight.title == "Opening highlight"

    unpublished = await service.publish_media(media.id, admin, is_published=False)
    assert unpublished.is_published is False
    assert await service.list_event_media(event.id) == []
