"""Media upload and highlight publishing workflow."""
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.core.permissions import user_has_scoped_role
from app.exceptions import PermissionDeniedError
from app.integrations.object_storage import get_object_storage_client
from app.modules.events.exceptions import EventNotFoundError
from app.modules.events.repository import EventRepository
from app.modules.identity.models import User
from app.modules.media.exceptions import (
    HighlightNotFoundError,
    InvalidMediaStateError,
    MediaConflictError,
    MediaNotFoundError,
)
from app.modules.media.models import Highlight, Media, MediaType
from app.modules.media.repository import HighlightRepository, MediaRepository
from app.modules.media.schemas import HighlightCreateIn, MediaUploadIn
from app.modules.rbac.models import RoleName


class MediaService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.events = EventRepository(db)
        self.media = MediaRepository(db)
        self.highlights = HighlightRepository(db)
        self.storage = get_object_storage_client()

    async def _get_event_or_raise(self, event_id: uuid.UUID):
        event = await self.events.get_by_id(event_id)
        if event is None:
            raise EventNotFoundError("Event not found.")
        return event

    async def _can_manage_media(self, actor: User, event_id: uuid.UUID) -> bool:
        return await user_has_scoped_role(
            self.db,
            actor.id,
            {RoleName.EVENT_MANAGER},
            event_id,
            allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN},
        )

    async def list_event_media(self, event_id: uuid.UUID, actor: User | None = None) -> list[Media]:
        """
        BUG FIX: this endpoint is deliberately public/unauthenticated
        (the mobile app and public event pages call it without a
        token) — but it was hardwired to ONLY ever return published
        items, with no way for Console staff to see drafts at all. That
        made the upload -> publish workflow structurally impossible:
        a newly uploaded item (always starts unpublished) could never
        be seen again in order to publish it.

        Now branches: an authenticated caller who can manage this
        event's media sees everything (draft + published, so they can
        actually find what to publish); everyone else — public/mobile,
        or an authenticated user without that permission — sees only
        published items, exactly as before.
        """
        await self._get_event_or_raise(event_id)
        can_see_drafts = actor is not None and await self._can_manage_media(actor, event_id)
        if can_see_drafts:
            items = await self.media.list_for_event(event_id)
        else:
            items = await self.media.list_published_for_event(event_id)
        # Both repository methods now eager-load `highlight` directly
        # (see the repository fix), so no manual patch-in is needed here.
        return sorted(items, key=lambda item: (item.highlight is None, item.sort_order, item.created_at))

    async def upload_media(self, event_id: uuid.UUID, actor: User, payload: MediaUploadIn) -> Media:
        await self._get_event_or_raise(event_id)
        if not await self._can_manage_media(actor, event_id):
            raise PermissionDeniedError("You don't have permission to upload media for this event.")

        stored = await self.storage.upload_media_asset(
            event_id=str(event_id),
            title=payload.title,
            media_type=payload.media_type.value,
            source_url=payload.source_url,
        )
        media = await self.media.create(
            event_id=event_id,
            uploaded_by=actor.id,
            title=payload.title,
            caption=payload.caption,
            category=payload.category,
            media_type=payload.media_type,
            storage_key=stored.storage_key,
            public_url=stored.public_url,
            is_published=False,
            sort_order=payload.sort_order,
        )
        if payload.is_highlight:
            highlight_title = payload.highlight_title or payload.title
            await self.highlights.create(
                event_id=event_id,
                media_id=media.id,
                title=highlight_title,
                description=payload.highlight_description,
                display_order=payload.highlight_order,
                is_active=True,
            )
        await write_audit_log(
            self.db,
            entity_type="media",
            entity_id=media.id,
            action="uploaded",
            actor_user_id=actor.id,
            after_value={"title": payload.title, "category": payload.category, "media_type": payload.media_type.value},
        )
        await self.db.commit()
        # Re-fetch via get_by_id (now eager-loads highlight) rather than
        # db.refresh(media), which only reloads column attributes, not
        # relationships — same fix as registrations/service.py's
        # create_registration for the identical MissingGreenlet issue.
        return await self.media.get_by_id(media.id)

    async def get_media_or_raise(self, media_id: uuid.UUID) -> Media:
        media = await self.media.get_by_id(media_id)
        if media is None:
            raise MediaNotFoundError("Media not found.")
        return media

    async def publish_media(self, media_id: uuid.UUID, actor: User, *, is_published: bool = True) -> Media:
        media = await self.get_media_or_raise(media_id)
        if not await self._can_manage_media(actor, media.event_id):
            raise PermissionDeniedError("You don't have permission to publish this media.")
        before = {"is_published": media.is_published}
        media.is_published = is_published
        media.published_by = actor.id if is_published else None
        media.published_at = datetime.now(timezone.utc) if is_published else None
        await write_audit_log(
            self.db,
            entity_type="media",
            entity_id=media.id,
            action="published" if is_published else "unpublished",
            actor_user_id=actor.id,
            before_value=before,
            after_value={"is_published": is_published},
        )
        await self.db.commit()
        # Same fix as upload_media — re-fetch with highlight eager-loaded.
        return await self.media.get_by_id(media.id)

    async def create_highlight(self, media_id: uuid.UUID, actor: User, payload: HighlightCreateIn) -> Highlight:
        media = await self.get_media_or_raise(media_id)
        if not await self._can_manage_media(actor, media.event_id):
            raise PermissionDeniedError("You don't have permission to manage highlights for this event.")
        existing = await self.highlights.get_by_media_id(media.id)
        if existing is not None:
            raise MediaConflictError("A highlight already exists for this media item.")
        highlight = await self.highlights.create(
            event_id=media.event_id,
            media_id=media.id,
            title=payload.title,
            description=payload.description,
            display_order=payload.display_order,
            is_active=True,
        )
        await self.db.commit()
        await self.db.refresh(highlight)
        return highlight