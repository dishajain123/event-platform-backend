"""Pydantic request/response contracts for the identity module."""
import uuid

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.identity.models import DocumentType, VerificationStatus
from app.modules.identity.phone import normalize_mobile_number
from app.modules.rbac.models import RoleName


class OTPRequestIn(BaseModel):
    mobile_number: str = Field(..., min_length=10, max_length=15)

    @field_validator("mobile_number")
    @classmethod
    def digits_only(cls, v: str) -> str:
        return normalize_mobile_number(v)


class OTPRequestOut(BaseModel):
    message: str
    resend_available_in_seconds: int


class EmailSignupIn(BaseModel):
    email: str = Field(..., min_length=5, max_length=255)
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if "@" not in value or value.startswith("@") or value.endswith("@"):
            raise ValueError("Enter a valid email address.")
        return value


class EmailLoginIn(EmailSignupIn):
    pass


class EmailCodeIn(BaseModel):
    email: str = Field(..., min_length=5, max_length=255)
    code: str = Field(..., min_length=4, max_length=8)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class PasswordResetRequestIn(BaseModel):
    email: str = Field(..., min_length=5, max_length=255)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class PasswordResetIn(EmailCodeIn):
    new_password: str = Field(..., min_length=8, max_length=128)


class OTPVerifyIn(BaseModel):
    mobile_number: str | None
    otp: str = Field(..., min_length=4, max_length=8)

    @field_validator("mobile_number")
    @classmethod
    def normalize_mobile_number_value(cls, v: str) -> str:
        return normalize_mobile_number(v)


class TokenPairOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshTokenIn(BaseModel):
    refresh_token: str


class LogoutIn(BaseModel):
    refresh_token: str | None = None
    access_token: str | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    mobile_number: str | None
    name: str | None
    email: str | None
    email_verified_at: datetime | None = None
    is_active: bool


class UserUpdateIn(BaseModel):
    """
    BUG FIX: found while building the mobile app's Profile screen —
    there was no way whatsoever for a user to change their own name or
    email; GET /users/me was the only endpoint touching a user's own
    profile at all. mobile_number is deliberately NOT editable here — a
    number change is a more sensitive operation (it's the account's
    login identity) than this plan's Phase 7 scope covers.
    """

    name: str | None = None
    email: str | None = None


class AccountRoleOut(BaseModel):
    role_name: RoleName
    event_id: uuid.UUID | None
    status: str


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    mobile_number: str
    name: str | None
    email: str | None
    email_verified_at: datetime | None = None
    is_active: bool
    roles: list[AccountRoleOut]


class AccountStatusUpdateIn(BaseModel):
    is_active: bool


class IdentityDocumentIn(BaseModel):
    document_type: DocumentType
    document_number: str = Field(..., min_length=4, max_length=64)


class IdentityDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_type: DocumentType
    verification_status: VerificationStatus


class AdminUserLookupIn(BaseModel):
    """
    Used only by Super Admin / Finance Admin to provision the console's
    global admin roles (Operations Admin, Finance Admin, Finance
    Operator, Finance Auditor) for a person who may never have opened
    the public app themselves. Finds the existing User for this mobile
    number, or creates a bare account if none exists yet — the same
    get_or_create the OTP-verify flow already uses internally, just
    exposed for this one admin-provisioning purpose. Does not log
    anyone in and issues no tokens.
    """

    mobile_number: str = Field(..., min_length=10, max_length=15)
    name: str | None = None

    @field_validator("mobile_number")
    @classmethod
    def digits_only(cls, v: str) -> str:
        return normalize_mobile_number(v)
