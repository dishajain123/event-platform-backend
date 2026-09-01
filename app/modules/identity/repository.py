"""
Pure DB access for the identity module — no business rules here.
Business rules (OTP validity, verification limits, etc.) live in service.py.
"""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.models import IdentityDocument, User
from app.modules.identity.phone import normalize_mobile_number


class UserRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def list_all(self) -> list[User]:
        result = await self.db.execute(select(User).order_by(User.created_at.desc()))
        return list(result.scalars().all())

    async def get_by_mobile_number(self, mobile_number: str) -> User | None:
        normalized = normalize_mobile_number(mobile_number)
        result = await self.db.execute(select(User).where(User.mobile_number == normalized))
        return result.scalar_one_or_none()

    async def create(self, mobile_number: str) -> User:
        user = User(mobile_number=normalize_mobile_number(mobile_number))
        self.db.add(user)
        await self.db.flush()
        return user

    async def get_or_create(self, mobile_number: str) -> tuple[User, bool]:
        """Returns (user, created) — used by the OTP-verify flow to auto-create
        a visitor account on first successful login."""
        normalized = normalize_mobile_number(mobile_number)
        existing = await self.get_by_mobile_number(normalized)
        if existing:
            return existing, False
        return await self.create(normalized), True


class IdentityDocumentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def add(self, user_id: uuid.UUID, document_type, encrypted_number: str) -> IdentityDocument:
        doc = IdentityDocument(
            user_id=user_id,
            document_type=document_type,
            document_number_encrypted=encrypted_number,
        )
        self.db.add(doc)
        await self.db.flush()
        return doc

    async def list_for_user(self, user_id: uuid.UUID) -> list[IdentityDocument]:
        result = await self.db.execute(
            select(IdentityDocument).where(IdentityDocument.user_id == user_id)
        )
        return list(result.scalars().all())
