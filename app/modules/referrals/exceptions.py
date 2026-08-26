from app.exceptions import ConflictError, NotFoundError, ValidationError


class ReferralNotFoundError(NotFoundError):
    error_code = "referral_not_found"


class ReferralRewardNotFoundError(NotFoundError):
    error_code = "referral_reward_not_found"


class InvalidReferralStateError(ValidationError):
    error_code = "invalid_referral_state"


class ReferralConflictError(ConflictError):
    error_code = "referral_conflict"
