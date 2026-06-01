"""Auth routes: register / login / logout / me / patch language.

JWT lives in an httpOnly Set-Cookie; the frontend never sees the token,
which sidesteps the localStorage XSS class. CORS must be configured with
allow_credentials=True (already true in __main__.py) so the browser
sends the cookie back on /api/* fetches.

During the optional-auth phase, the rest of /api/* still works without
a cookie. Tightening to required auth is a follow-up — just swap the
optional_user dependency for current_user on the relevant routers.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, EmailStr, Field

from api.auth.dependency import current_user
from api.auth.jwt import encode_token
from api.auth.password import hash_password, verify_password
from api.config import get_settings
from api.domain.user import Language, User, UserPublic
from api.repository.errors import NotFoundError, RepositoryError
from api.runtime import get_repository

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    language: Language = "ru"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UpdateMeRequest(BaseModel):
    language: Language | None = None


def _set_auth_cookie(response: Response, token: str) -> None:
    s = get_settings().auth
    response.set_cookie(
        key=s.cookie_name,
        value=token,
        max_age=s.cookie_max_age_s,
        httponly=True,
        samesite="lax",
        secure=s.cookie_secure,
        path="/",
    )


def _clear_auth_cookie(response: Response) -> None:
    s = get_settings().auth
    response.delete_cookie(key=s.cookie_name, path="/")


@router.post(
    "/register",
    response_model=UserPublic,
    status_code=status.HTTP_201_CREATED,
)
async def register(body: RegisterRequest, response: Response) -> UserPublic:
    s = get_settings().auth
    if not s.register_open:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="registration is closed on this deploy",
        )
    repo = get_repository()
    try:
        user = User(
            email=body.email,
            password_hash=hash_password(body.password),
            language=body.language,
        )
        created = await repo.create_user(user)
    except RepositoryError as e:
        # Email collision lands here.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    _set_auth_cookie(response, encode_token(str(created.id)))
    return UserPublic.of(created)


@router.post("/login", response_model=UserPublic)
async def login(body: LoginRequest, response: Response) -> UserPublic:
    repo = get_repository()
    try:
        user = await repo.get_user_by_email(body.email)
    except NotFoundError:
        # Generic message — don't leak which half (email vs password) failed.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid email or password",
        )
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid email or password",
        )
    _set_auth_cookie(response, encode_token(str(user.id)))
    return UserPublic.of(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> Response:
    _clear_auth_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=UserPublic)
async def get_me(user: Annotated[User, Depends(current_user)]) -> UserPublic:
    return UserPublic.of(user)


@router.patch("/me", response_model=UserPublic)
async def patch_me(
    body: UpdateMeRequest,
    user: Annotated[User, Depends(current_user)],
) -> UserPublic:
    repo = get_repository()
    if body.language is not None and body.language != user.language:
        user = await repo.update_user_language(user.id, body.language)
    return UserPublic.of(user)
