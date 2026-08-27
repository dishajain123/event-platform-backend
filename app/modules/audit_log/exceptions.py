from app.exceptions import ValidationError


class InvalidAuditLogFilterError(ValidationError):
    error_code = "invalid_audit_log_filter"