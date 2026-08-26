from app.exceptions import ConflictError, NotFoundError, ValidationError


class PaymentNotFoundError(NotFoundError):
    error_code = "payment_not_found"


class RefundNotFoundError(NotFoundError):
    error_code = "refund_not_found"


class DiscountCodeNotFoundError(NotFoundError):
    error_code = "discount_code_not_found"


class InvalidPaymentStateError(ValidationError):
    error_code = "invalid_payment_state"


class InvalidRefundStateError(ValidationError):
    error_code = "invalid_refund_state"


class PaymentVerificationFailedError(ValidationError):
    error_code = "payment_verification_failed"


class DuplicatePaymentError(ConflictError):
    error_code = "duplicate_payment"
