from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import EmailStr, Field

from .types import DomainModel, Id, new_id, utcnow


Language = Literal["ru", "en"]


class User(DomainModel):
    id: Id = Field(default_factory=new_id)
    email: EmailStr
    password_hash: str
    language: Language = "ru"
    created_at: datetime = Field(default_factory=utcnow)


class UserPublic(DomainModel):
    """User-facing projection — never expose password_hash."""

    id: Id
    email: EmailStr
    language: Language
    created_at: datetime

    @classmethod
    def of(cls, u: User) -> "UserPublic":
        return cls(
            id=u.id,
            email=u.email,
            language=u.language,
            created_at=u.created_at,
        )
