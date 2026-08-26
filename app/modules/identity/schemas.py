"""Pydantic request/response contracts for the identity module."""
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.identity.models import DocumentType, VerificationStatus


class OTPRequestIn(BaseModel):
    mobile_number: str = Field(..., min_length=10, max_length=15)

    @field_validator("mobile_number")
    @classmethod
    def digits_only(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned.lstrip("+").isdigit():
            raise ValueError("mobile_number must contain only digits (optionally with a leading +)")
        return cleaned


class OTPRequestOut(BaseModel):
    message: str
    resend_available_in_seconds: int


class OTPVerifyIn(BaseModel):
    mobile_number: str
    otp: str = Field(..., min_length=4, max_length=8)


class TokenPairOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshTokenIn(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    mobile_number: str
    name: str | None
    email: str | None
    is_active: bool


class IdentityDocumentIn(BaseModel):
    document_type: DocumentType
    document_number: str = Field(..., min_length=4, max_length=64)


class IdentityDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_type: DocumentType
    verification_status: VerificationStatus