from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TypedDict

import jwt

from api.config import get_settings


class TokenPayload(TypedDict):
    sub: str
    exp: int


def encode_token(user_id: str) -> str:
    s = get_settings().auth
    exp = datetime.now(tz=timezone.utc) + timedelta(seconds=s.cookie_max_age_s)
    return jwt.encode(
        {"sub": user_id, "exp": int(exp.timestamp())},
        s.secret,
        algorithm="HS256",
    )


def decode_token(token: str) -> TokenPayload | None:
    s = get_settings().auth
    try:
        payload = jwt.decode(token, s.secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    sub = payload.get("sub")
    exp = payload.get("exp")
    if not isinstance(sub, str) or not isinstance(exp, int):
        return None
    return {"sub": sub, "exp": exp}
