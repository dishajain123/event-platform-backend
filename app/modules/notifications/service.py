"""Notification targeting and dispatch orchestration."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.core.permissions import user_has_scoped_role
from app.exceptions import PermissionDeniedError
from app.integrations.notification_providers import (
    NotificationProviderError,
    get_email_provider,
    get_push_provider,
)
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
    DeviceToken,
    DeviceTokenPlatform,
    Notification,
    NotificationChannel,
    NotificationDeliveryStatus,
    NotificationTemplate,
    NotificationPreference,
)
from app.modules.notifications.repository import (
    DeviceTokenRepository,
    NotificationPreferenceRepository,
    NotificationRepository,
    NotificationTemplateRepository,
)
from app.modules.rbac.models import RoleName
from app.modules.registrations.models import ACTIVE_REGISTRATION_STATUSES
from app.modules.registrations.repository import RegistrationRepository
from app.config import get_settings


class NotificationService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.settings = get_settings()
        self.notifications = NotificationRepository(db)
        self.templates = NotificationTemplateRepository(db)
        self.device_tokens = DeviceTokenRepository(db)
        self.preferences = NotificationPreferenceRepository(db)
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

    async def list_notifications_for_event(self, actor: User, event_id: uuid.UUID) -> list[Notification]:
        await self._get_event_or_raise(event_id)
        if not await self._can_manage_event(actor, event_id):
            raise PermissionDeniedError("You don't have permission to view notifications for this event.")
        return await self.notifications.list_for_event(event_id)

    async def page_notifications_for_event(self, actor: User, event_id: uuid.UUID, *, page=1, page_size=25):
        await self._get_event_or_raise(event_id)
        if not await self._can_manage_event(actor, event_id):
            raise PermissionDeniedError("You don't have permission to view notifications for this event.")
        return await self.notifications.page_for_event(event_id, page=page, page_size=page_size)

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
        registrations = await self.registrations.list_for_event(event_id)
        if recipient_user_ids:
            allowed = {registration.user_id for registration in registrations}
            return list(dict.fromkeys(user_id for user_id in recipient_user_ids if user_id in allowed))
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
        notification_type: str = "operational",
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
        target_user_ids = [
            user_id
            for user_id in target_user_ids
            if await self._preference_enabled(user_id, notification_type)
        ]
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
                    notification_type=notification_type,
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

    async def queue_capacity_warning(
        self, *, event_id: uuid.UUID, registered_count: int, capacity: int
    ) -> list[Notification]:
        """Queue one push warning when an event reaches 80% capacity."""
        registrations = await self.registrations.list_for_event(event_id)
        recipient_ids = list(
            dict.fromkeys(
                registration.user_id
                for registration in registrations
                if registration.status in ACTIVE_REGISTRATION_STATUSES
            )
        )
        created: list[Notification] = []
        for recipient_id in recipient_ids:
            dedupe_key = f"capacity-warning:{event_id}:{recipient_id}"
            if await self.notifications.get_by_dedupe_key(dedupe_key):
                continue
            if not await self._preference_enabled(recipient_id, "operational"):
                continue
            created.append(
                await self.notifications.create(
                    event_id=event_id,
                    recipient_user_id=recipient_id,
                    template_id=None,
                    channel=NotificationChannel.PUSH,
                    title="Limited seats available",
                    body="Limited seats available — Register now!",
                    target_metadata={
                        "capacity_warning": True,
                        "registration_status": "limited",
                        "registered_count": registered_count,
                        "capacity": capacity,
                        "deep_link": f"/events/{event_id}",
                    },
                    delivery_status=NotificationDeliveryStatus.QUEUED,
                    notification_type="operational",
                    dedupe_key=dedupe_key,
                )
            )
        return created

    async def _preference_enabled(self, user_id: uuid.UUID, notification_type: str) -> bool:
        preference = await self.preferences.get_for_user(user_id)
        if preference is None:
            return True
        field = {
            "event_reminder": "event_reminders",
            "registration_confirmation": "registration_updates",
            "payment_update": "registration_updates",
            "cancellation_refund": "cancellation_refund_updates",
            "event_change": "event_changes",
            "feedback_reminder": "event_reminders",
            "marketing": "marketing_notifications",
        }.get(notification_type, "operational_notifications")
        return bool(getattr(preference, field))

    async def get_or_create_preferences(self, user_id: uuid.UUID) -> NotificationPreference:
        preference = await self.preferences.get_for_user(user_id)
        if preference is None:
            preference = NotificationPreference(user_id=user_id)
            self.db.add(preference)
            await self.db.flush()
        return preference

    async def update_preferences(self, user: User, values: dict) -> NotificationPreference:
        preference = await self.get_or_create_preferences(user.id)
        for key, value in values.items():
            if value is not None and hasattr(preference, key):
                setattr(preference, key, value)
        await self.db.commit()
        await self.db.refresh(preference)
        return preference

    async def register_device(self, user: User, token: str, platform: DeviceTokenPlatform) -> DeviceToken:
        device = await self.device_tokens.get_by_token(token)
        now = datetime.now(timezone.utc)
        if device is None:
            device = DeviceToken(user_id=user.id, token=token, platform=platform, last_seen_at=now)
            self.db.add(device)
        else:
            device.user_id = user.id
            device.platform = platform
            device.is_active = True
            device.last_seen_at = now
            device.failure_count = 0
        await self.db.commit()
        await self.db.refresh(device)
        return device

    async def remove_device(self, user: User, device_id: uuid.UUID) -> None:
        device = await self.device_tokens.get_by_id(device_id)
        if device is None or device.user_id != user.id:
            raise PermissionDeniedError("You cannot remove another user's device token.")
        device.is_active = False
        await self.db.commit()

    async def _queue_automated(
        self,
        *,
        event_id: uuid.UUID,
        user_id: uuid.UUID,
        title: str,
        body: str,
        notification_type: str,
        dedupe_key: str,
        target_metadata: dict,
    ) -> Notification | None:
        if not await self._preference_enabled(user_id, notification_type):
            return None
        if await self.notifications.get_by_dedupe_key(dedupe_key):
            return None
        return await self.notifications.create(
            event_id=event_id,
            recipient_user_id=user_id,
            template_id=None,
            channel=NotificationChannel.PUSH,
            title=title,
            body=body,
            target_metadata=target_metadata,
            delivery_status=NotificationDeliveryStatus.QUEUED,
            notification_type=notification_type,
            dedupe_key=dedupe_key,
        )

    async def queue_automated_notifications(self) -> list[uuid.UUID]:
        """Create idempotent reminders/status messages for the current window."""
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from app.modules.events.models import Event, EventStatus
        from app.modules.config_engine.registration_state import parse_registration_end_at
        from app.modules.payments.models import PaymentStatus
        from app.modules.registrations.models import Registration, RegistrationStatus

        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            select(Registration)
            .options(selectinload(Registration.payment))
            .where(Registration.status.not_in({RegistrationStatus.CANCELLED, RegistrationStatus.REJECTED}))
        )
        registrations = list(result.scalars().all())
        event_ids = {registration.event_id for registration in registrations}
        events = {}
        if event_ids:
            event_result = await self.db.execute(
                select(Event).options(selectinload(Event.configuration)).where(Event.id.in_(event_ids))
            )
            events = {event.id: event for event in event_result.scalars().all()}
        created: list[uuid.UUID] = []
        for registration in registrations:
            event = events.get(registration.event_id)
            if event is None:
                continue
            base_metadata = {
                "event_id": str(event.id),
                "registration_id": str(registration.id),
                "deep_link": f"/registrations/{registration.id}",
            }
            if registration.status == RegistrationStatus.CONFIRMED:
                notification = await self._queue_automated(
                    event_id=event.id,
                    user_id=registration.user_id,
                    title="Registration confirmed",
                    body=f"Your registration for {event.name} is confirmed.",
                    notification_type="registration_confirmation",
                    dedupe_key=f"registration-confirmed:{registration.id}",
                    target_metadata=base_metadata,
                )
                if notification:
                    created.append(notification.id)
            if registration.payment is not None and registration.payment.status == PaymentStatus.FAILED:
                notification = await self._queue_automated(
                    event_id=event.id,
                    user_id=registration.user_id,
                    title="Payment needs attention",
                    body=f"Payment for {event.name} was not completed. Please try again.",
                    notification_type="payment_update",
                    dedupe_key=f"payment-failed:{registration.id}",
                    target_metadata=base_metadata,
                )
                if notification:
                    created.append(notification.id)
            if registration.status in {RegistrationStatus.REFUND_PENDING, RegistrationStatus.REFUND_FAILED, RegistrationStatus.CANCELLED}:
                notification = await self._queue_automated(
                    event_id=event.id,
                    user_id=registration.user_id,
                    title="Registration status updated",
                    body=f"Your registration for {event.name} is now {registration.status.value.replace('_', ' ')}.",
                    notification_type="cancellation_refund",
                    dedupe_key=f"registration-status:{registration.id}:{registration.status.value}",
                    target_metadata=base_metadata,
                )
                if notification:
                    created.append(notification.id)
            if event.status != EventStatus.ARCHIVED:
                event_start = event.start_date
                if event_start.tzinfo is None:
                    event_start = event_start.replace(tzinfo=timezone.utc)
                hours_to_event = (event_start - now).total_seconds() / 3600
                if 23 <= hours_to_event <= 25:
                    notification = await self._queue_automated(
                        event_id=event.id,
                        user_id=registration.user_id,
                        title="Event starts tomorrow",
                        body=f"{event.name} starts tomorrow. We look forward to seeing you.",
                        notification_type="event_reminder",
                        dedupe_key=f"event-reminder-24h:{registration.id}",
                        target_metadata={**base_metadata, "reminder": "24h"},
                    )
                    if notification:
                        created.append(notification.id)
                registration_end = parse_registration_end_at(
                    event.configuration.details if event.configuration else None
                )
                if registration_end is not None:
                    if registration_end.tzinfo is None:
                        registration_end = registration_end.replace(tzinfo=timezone.utc)
                    hours_to_deadline = (registration_end - now).total_seconds() / 3600
                    if 23 <= hours_to_deadline <= 25:
                        notification = await self._queue_automated(
                            event_id=event.id,
                            user_id=registration.user_id,
                            title="Registration closes tomorrow",
                            body=f"Registration for {event.name} closes tomorrow.",
                            notification_type="event_reminder",
                            dedupe_key=f"registration-deadline-24h:{registration.id}",
                            target_metadata={**base_metadata, "reminder": "registration_deadline_24h"},
                        )
                        if notification:
                            created.append(notification.id)
            event_end = event.end_date
            if event_end.tzinfo is None:
                event_end = event_end.replace(tzinfo=timezone.utc)
            hours_since_event = (now - event_end).total_seconds() / 3600
            if registration.status in {RegistrationStatus.CONFIRMED, RegistrationStatus.CHECKED_IN} and 0 <= hours_since_event <= 24:
                notification = await self._queue_automated(
                    event_id=event.id,
                    user_id=registration.user_id,
                    title="Tell us about the event",
                    body=f"Share your feedback for {event.name}.",
                    notification_type="feedback_reminder",
                    dedupe_key=f"feedback-reminder:{registration.id}",
                    target_metadata={**base_metadata, "deep_link": f"/events/{event.id}/feedback"},
                )
                if notification:
                    created.append(notification.id)
        # Volunteer shift reminders use the same idempotent scheduler and
        # delivery preferences as every other automated notification.
        from app.modules.volunteer_shifts.models import VolunteerAssignmentStatus, VolunteerShift, VolunteerShiftAssignment
        shift_rows = await self.db.execute(
            select(VolunteerShiftAssignment, VolunteerShift).join(
                VolunteerShift, VolunteerShift.id == VolunteerShiftAssignment.shift_id
            ).where(
                VolunteerShiftAssignment.status.in_({VolunteerAssignmentStatus.APPROVED, VolunteerAssignmentStatus.ACTIVE}),
                VolunteerShift.starts_at >= now,
                VolunteerShift.starts_at <= now + timedelta(hours=25),
            )
        )
        for assignment, shift in shift_rows.all():
            starts_at = shift.starts_at
            if starts_at.tzinfo is None:
                starts_at = starts_at.replace(tzinfo=timezone.utc)
            hours_to_shift = (starts_at - now).total_seconds() / 3600
            if 23 <= hours_to_shift <= 25:
                notification = await self._queue_automated(
                    event_id=shift.event_id,
                    user_id=assignment.user_id,
                    title="Volunteer shift reminder",
                    body=f"Your volunteer shift '{shift.title}' starts tomorrow.",
                    notification_type="volunteer_shift",
                    dedupe_key=f"volunteer-shift-reminder-24h:{assignment.id}",
                    target_metadata={"shift_id": str(shift.id), "assignment_id": str(assignment.id), "deep_link": "/volunteers/shifts/mine"},
                )
                if notification:
                    created.append(notification.id)
        if created:
            await self.db.commit()
        return created

    async def queue_event_change(self, event_id: uuid.UUID, *, reason: str) -> list[uuid.UUID]:
        """Notify active participants once for an event change revision."""
        from app.modules.events.models import Event

        event = await self.events.get_by_id(event_id)
        if event is None:
            return []
        registrations = await self.registrations.list_for_event(event_id)
        revision = event.updated_at.isoformat()
        created: list[uuid.UUID] = []
        for registration in registrations:
            if registration.status.value in {"cancelled", "rejected"}:
                continue
            notification = await self._queue_automated(
                event_id=event_id,
                user_id=registration.user_id,
                title="Event information changed",
                body=f"{event.name}: {reason}",
                notification_type="event_change",
                dedupe_key=f"event-change:{event_id}:{revision}:{registration.user_id}",
                target_metadata={
                    "event_id": str(event_id),
                    "registration_id": str(registration.id),
                    "deep_link": f"/events/{event_id}",
                },
            )
            if notification:
                created.append(notification.id)
        if created:
            await self.db.commit()
            if self.settings.environment == "production":
                from app.workers.notification_tasks import deliver_notification_batch

                deliver_notification_batch.delay([str(notification_id) for notification_id in created])
            else:
                for notification_id in created:
                    await self.deliver_notification(notification_id)
        return created

    async def deliver_notification(self, notification_id: uuid.UUID) -> Notification:
        notification = await self.notifications.get_by_id(notification_id)
        if notification is None:
            raise NotificationNotFoundError("Notification not found.")
        if notification.delivery_status == NotificationDeliveryStatus.SENT:
            return notification
        if notification.delivery_status == NotificationDeliveryStatus.FAILED and notification.attempt_count >= self.settings.notification_max_attempts:
            return notification

        recipient = await self.db.get(User, notification.recipient_user_id)
        if recipient is None:
            raise NotificationDispatchError("Recipient user not found.")

        notification.attempt_count += 1
        try:
            if notification.channel == NotificationChannel.EMAIL:
                if not recipient.email:
                    raise NotificationDispatchError("Recipient does not have an email address.")
                provider_message_id = await get_email_provider(self.settings).send(
                    recipient=recipient.email, subject=notification.title, body=notification.body
                )
            elif notification.channel == NotificationChannel.SMS:
                provider_message_id = await send_notification_sms(recipient.mobile_number, notification.body)
            else:
                devices = await self.device_tokens.get_active_for_user(recipient.id)
                if not devices:
                    if self.settings.notification_push_provider == "development":
                        provider_message_id = await get_push_provider(self.settings).send(
                            token=str(recipient.id),
                            title=notification.title,
                            body=notification.body,
                            data=notification.target_metadata or {},
                        )
                    else:
                        raise NotificationDispatchError("Recipient has no active push devices.")
                else:
                    message_ids: list[str] = []
                    for device in devices:
                        try:
                            message_ids.append(
                                await get_push_provider(self.settings).send(
                                    token=device.token,
                                    title=notification.title,
                                    body=notification.body,
                                    data=notification.target_metadata or {},
                                )
                            )
                            device.failure_count = 0
                        except NotificationProviderError as exc:
                            device.failure_count += 1
                            if exc.invalid_recipient or device.failure_count >= self.settings.notification_max_attempts:
                                device.is_active = False
                            if not exc.invalid_recipient:
                                raise
                    if not message_ids:
                        raise NotificationDispatchError("All push devices rejected the notification.")
                    provider_message_id = ",".join(message_ids)
        except Exception as exc:
            notification.delivery_status = NotificationDeliveryStatus.FAILED
            notification.last_error = str(exc)[:1000]
            notification.failed_at = datetime.now(timezone.utc)
            await self.db.commit()
            raise NotificationDispatchError(str(exc)) from exc

        notification.delivery_status = NotificationDeliveryStatus.SENT
        notification.provider_message_id = provider_message_id
        notification.sent_at = datetime.now(timezone.utc)
        notification.delivered_at = notification.sent_at
        notification.last_error = None
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
