from app.exceptions import AppError, ConflictError, NotFoundError, RateLimitedError, ValidationError


class UserNotFoundError(NotFoundError):
    error_code = "user_not_found"


class InvalidOTPError(ValidationError):
    error_code = "invalid_otp"


class OTPExpiredError(ValidationError):
    error_code = "otp_expired"


class OTPResendTooSoonError(RateLimitedError):
    error_code = "otp_resend_too_soon"


class TooManyOTPAttemptsError(RateLimitedError):
    error_code = "too_many_otp_attempts"


class InvalidTokenError(AppError):
    status_code = 401
    error_code = "invalid_token"


class DuplicateIdentityDocumentError(ConflictError):
    error_code = "duplicate_identity_document"