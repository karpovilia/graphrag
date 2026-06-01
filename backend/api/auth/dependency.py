from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Cookie, Depends, HTTPException, status

from api.domain.types import Id
from api.domain.user import User
from api.repository.errors import NotFoundError
from api.runtime import get_repository

from .jwt import decode_token


async def optional_user(
    auth: Annotated[str | None, Cookie()] = None,
) -> User | None:
    """Return the logged-in user, or None when there's no/invalid cookie.

    Use on routes that work for both anonymous and logged-in callers
    (e.g. read-only catalogue endpoints during the optional-auth phase).
    """

    if auth is None:
        return None
    payload = decode_token(auth)
    if payload is None:
        return None
    try:
        user_id = Id(UUID(payload["sub"]))
    except (ValueError, TypeError):
        return None
    repo = get_repository()
    try:
        return await repo.get_user(user_id)
    except NotFoundError:
        return None


async def current_user(
    user: Annotated[User | None, Depends(optional_user)],
) -> User:
    """Required auth — 401 when missing/invalid cookie."""

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="not authenticated",
        )
    return user
