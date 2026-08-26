"""Notification targeting and dispatch orchestration."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.core.permissions import user_has_scoped_role
from app.exceptions import PermissionDeniedError
from app.integrations.email_provider import send_notification_email
from app.integrations.push_notifications import send_push_notification
from app.integrations.sms_provider import send_notification_sms
from app.modules.events.exceptions import EventNotFoundError
from app.modules.events.repository import EventRepository
from app.modules.identity.models import User
from app.modules.notifications.exceptions import (
    InvalidNotificationTargetError,
    NotificationDispatchError,
    NotificationNotFoundError,
)
from app.modules.notifications.models import (
    Notification,
    NotificationChannel,
    NotificationDeliveryStatus,
    NotificationTemplate,
)
from app.modules.notifications.repository import NotificationRepository, NotificationTemplateRepository
from app.modules.rbac.models import RoleName
from app.modules.registrations.models import Registration
from app.modules.registrations.repository import RegistrationRepository
from app.config import get_settings


class NotificationService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.settings = get_settings()
        self.notifications = NotificationRepository(db)
        self.templates = NotificationTemplateRepository(db)
        self.registrations = RegistrationRepository(db)
        self.events = EventRepository(db)

    async def _can_manage_event(self, actor: User, event_id: uuid.UUID) -> bool:
        return await user_has_scoped_role(
            self.db,
            actor.id,
            {RoleName.EVENT_MANAGER, RoleName.EVENT_COORDINATOR},
            event_id,
            allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN},
        )

    async def _get_event_or_raise(self, event_id: uuid.UUID):
        event = await self.events.get_by_id(event_id)
        if event is None:
            raise EventNotFoundError("Event not found.")
        return event

    async def list_my_notifications(self, user: User) -> list[Notification]:
        return await self.notifications.list_for_user(user.id)

    async def list_templates(self) -> list[NotificationTemplate]:
        return await self.templates.list_all()

    async def _resolve_targets(
        self,
        *,
        event_id: uuid.UUID,
        participation_types: list[str],
        registration_statuses: list,
        recipient_user_ids: list[uuid.UUID],
    ) -> list[uuid.UUID]:
        if recipient_user_ids:
            return list(dict.fromkeys(recipient_user_ids))

        registrations = await self.registrations.list_for_event(event_id)
        selected: list[uuid.UUID] = []
        for registration in registrations:
            if participation_types and registration.participation_type not in participation_types:
                continue
            if registration_statuses and registration.status not in set(registration_statuses):
                continue
            selected.append(registration.user_id)
        return list(dict.fromkeys(selected))

    async def send_notifications(
        self,
        *,
        actor: User,
        title: str,
        body: str,
        channels: list[NotificationChannel],
        event_id: uuid.UUID,
        participation_types: list[str],
        registration_statuses: list,
        recipient_user_ids: list[uuid.UUID],
        template_code: str | None = None,
    ) -> list[Notification]:
        await self._get_event_or_raise(event_id)
        if not await self._can_manage_event(actor, event_id):
            raise PermissionDeniedError("You don't have permission to send notifications for this event.")

        target_user_ids = await self._resolve_targets(
            event_id=event_id,
            participation_types=participation_types,
            registration_statuses=registration_statuses,
            recipient_user_ids=recipient_user_ids,
        )
        if not target_user_ids:
            raise InvalidNotificationTargetError("No recipients matched the provided filters.")
        if not channels:
            raise InvalidNotificationTargetError("At least one delivery channel is required.")

        template = None
        if template_code is not None:
            template = await self.templates.get_by_code(template_code)
            if template is None or not template.is_active:
                raise InvalidNotificationTargetError("Notification template not found or inactive.")

        created: list[Notification] = []
        for recipient_user_id in target_user_ids:
            for channel in channels:
                notification = await self.notifications.create(
                    event_id=event_id,
                    recipient_user_id=recipient_user_id,
                    template_id=template.id if template else None,
                    channel=channel,
                    title=title,
                    body=body,
                    target_metadata={
                        "participation_types": participation_types,
                        "registration_statuses": [status.value for status in registration_statuses],
                    },
                    delivery_status=NotificationDeliveryStatus.QUEUED,
                )
                created.append(notification)

        await write_audit_log(
            self.db,
            entity_type="notification",
            entity_id=created[0].id,
            action="queued",
            actor_user_id=actor.id,
            after_value={
                "event_id": str(event_id),
                "recipient_count": len(target_user_ids),
                "channel_count": len(channels),
            },
        )
        await self.db.commit()
        for notification in created:
            await self.db.refresh(notification)

        if self.settings.environment == "production":
            from app.workers.notification_tasks import deliver_notification_batch

            deliver_notification_batch.delay([str(notification.id) for notification in created])
        else:
            for notification in created:
                await self.deliver_notification(notification.id)

        for notification in created:
            await self.db.refresh(notification)

        return created

    async def deliver_notification(self, notification_id: uuid.UUID) -> Notification:
        notification = await self.notifications.get_by_id(notification_id)
        if notification is None:
            raise NotificationNotFoundError("Notification not found.")
        if notification.delivery_status == NotificationDeliveryStatus.SENT:
            return notification

        recipient = await self.db.get(User, notification.recipient_user_id)
        if recipient is None:
            raise NotificationDispatchError("Recipient user not found.")

        try:
            if notification.channel == NotificationChannel.EMAIL:
                if not recipient.email:
                    raise NotificationDispatchError("Recipient does not have an email address.")
                provider_message_id = await send_notification_email(
                    recipient.email, notification.title, notification.body
                )
            elif notification.channel == NotificationChannel.SMS:
                provider_message_id = await send_notification_sms(recipient.mobile_number, notification.body)
            else:
                provider_message_id = await send_push_notification(
                    str(recipient.id), notification.title, notification.body
                )
        except Exception as exc:
            notification.delivery_status = NotificationDeliveryStatus.FAILED
            await self.db.commit()
            raise NotificationDispatchError(str(exc)) from exc

        notification.delivery_status = NotificationDeliveryStatus.SENT
        notification.provider_message_id = provider_message_id
        notification.sent_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(notification)
        return notification

    async def mark_read(self, notification_id: uuid.UUID, actor: User) -> Notification:
        notification = await self.notifications.get_by_id(notification_id)
        if notification is None:
            raise NotificationNotFoundError("Notification not found.")
        if notification.recipient_user_id != actor.id:
            raise PermissionDeniedError("You cannot update another user's notification.")
        notification.read_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(notification)
        return notification
