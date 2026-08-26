from app.exceptions import ConflictError, NotFoundError, ValidationError


class NotificationNotFoundError(NotFoundError):
    error_code = "notification_not_found"


class NotificationTemplateNotFoundError(NotFoundError):
    error_code = "notification_template_not_found"


class InvalidNotificationTargetError(ValidationError):
    error_code = "invalid_notification_target"


class NotificationDispatchError(ConflictError):
    error_code = "notification_dispatch_error"
