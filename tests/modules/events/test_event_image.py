"""Event cover image: normalization, replace/remove, and permissions."""
import io
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image
from sqlalchemy import select

from app.exceptions import PermissionDeniedError
from app.modules.events.exceptions import InvalidEventImageError
from app.modules.events.image import process_event_image
from app.modules.events.service import EventService
from app.modules.identity.models import User
from app.modules.rbac.models import Role, RoleAssignment, RoleName


async def _assign_role(db_session, user: User, role_name: RoleName, event_id=None):
    role = (await db_session.execute(select(Role).where(Role.name == role_name))).scalar_one()
    db_session.add(RoleAssignment(user_id=user.id, role_id=role.id, event_id=event_id))
    await db_session.flush()


async def _make_event(db_session):
    creator = User(mobile_number="+919700000001")
    admin = User(mobile_number="+919700000002")
    db_session.add_all([creator, admin])
    await db_session.flush()
    start = datetime.now(timezone.utc) + timedelta(days=5)
    event = await EventService(db_session).create_event(
        created_by=creator.id,
        name="Cover Image Event",
        description="fixture",
        category="sample",
        start_date=start,
        end_date=start + timedelta(days=1),
        organization_id=None,
    )
    await _assign_role(db_session, admin, RoleName.SUPER_ADMIN)
    return event, admin


def _png_bytes(width=2000, height=800, color=(10, 120, 200)):
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, format="PNG")
    return buf.getvalue()


def test_process_event_image_normalizes_to_fixed_16_9_jpeg():
    out = process_event_image(_png_bytes(3000, 1000))
    with Image.open(io.BytesIO(out)) as img:
        assert img.format == "JPEG"
        assert img.size == (1200, 675)


def test_process_event_image_rejects_non_image():
    with pytest.raises(InvalidEventImageError):
        process_event_image(b"this is definitely not an image")


@pytest.mark.asyncio
async def test_set_replace_and_remove_event_image(db_session):
    event, admin = await _make_event(db_session)
    service = EventService(db_session)

    updated = await service.set_event_image(
        event.id, admin.id, raw=_png_bytes(), content_type="image/png"
    )
    assert updated.image_url is not None
    assert updated.image_storage_key is not None
    first_key = str(updated.image_storage_key)
    first_url = str(updated.image_url)

    replaced = await service.set_event_image(
        event.id, admin.id, raw=_png_bytes(color=(200, 30, 30)), content_type="image/png"
    )
    assert replaced.image_storage_key != first_key
    assert replaced.image_url != first_url

    removed = await service.remove_event_image(event.id, admin.id)
    assert removed.image_url is None
    assert removed.image_storage_key is None


@pytest.mark.asyncio
async def test_set_event_image_rejects_oversize_and_wrong_type(db_session):
    event, admin = await _make_event(db_session)
    service = EventService(db_session)

    with pytest.raises(InvalidEventImageError):
        await service.set_event_image(
            event.id, admin.id, raw=b"x" * (6 * 1024 * 1024), content_type="image/png"
        )

    with pytest.raises(InvalidEventImageError):
        await service.set_event_image(
            event.id, admin.id, raw=_png_bytes(), content_type="application/pdf"
        )


@pytest.mark.asyncio
async def test_to_response_exposes_image_url(db_session):
    event, admin = await _make_event(db_session)
    service = EventService(db_session)
    await service.set_event_image(event.id, admin.id, raw=_png_bytes(), content_type="image/png")
    response = await service.to_response(await service.get_event_or_raise(event.id))
    assert response.image_url is not None
