"""Login/parol autentifikatsiyasi: bcrypt + JWT. Har bir foydalanuvchi alohida avto-ID oladi."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Query, WebSocket, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.memory.database import SessionLocal, User, get_session

ALGO = "HS256"
bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        return False


def create_token(user_id: str, kind: str = "access", minutes: int | None = None) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=minutes or settings.ACCESS_TOKEN_MINUTES)
    iat = datetime.now(timezone.utc).timestamp()
    return jwt.encode({"sub": user_id, "kind": kind, "exp": exp, "iat_ms": int(iat * 1000)}, settings.SECRET_KEY,
                      algorithm=ALGO)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGO])
    except jwt.PyJWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Token yaroqsiz: {e}") from e


async def _user_from_token(token: str, db: AsyncSession) -> User:
    payload = decode_token(token)
    if payload.get("kind") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Noto'g'ri token turi")
    user = await db.get(User, payload["sub"])
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Foydalanuvchi topilmadi")
    from backend.security.services import get_policy
    after = (await get_policy(user.id)).get("tokens_after") or 0
    if after and payload.get("iat_ms", 0) / 1000 < after:     # admin pressed "barcha sessiyalardan chiqarish"
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessiya administrator tomonidan yakunlangan")
    return user


async def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    token: str | None = Query(default=None, include_in_schema=False),
    db: AsyncSession = Depends(get_session),
) -> User:
    raw = creds.credentials if creds else token
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Login talab qilinadi")
    return await _user_from_token(raw, db)


async def admin_user(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Faqat admin uchun")
    return user


async def ws_user(ws: WebSocket) -> User | None:
    token = ws.query_params.get("token")
    if not token:
        return None
    async with SessionLocal() as db:
        try:
            return await _user_from_token(token, db)
        except HTTPException:
            return None


async def register_user(db: AsyncSession, username: str, password: str, full_name: str = "",
                        language: str = "uz", by_admin: bool = False) -> User:
    username = username.strip().lower()
    if len(username) < 3 or len(password) < 8:
        raise HTTPException(400, "Login kamida 3, parol kamida 8 belgidan iborat bo'lsin")
    exists = await db.scalar(select(User).where(User.username == username))
    if exists:
        raise HTTPException(409, "Bu login band")
    first = (await db.scalar(select(User.id).limit(1))) is None
    if not first and not by_admin:
        from backend.security.services import load_config
        if not load_config()["registration_open"]:
            raise HTTPException(403, "Ro'yxatdan o'tish yopiq. Hisobni administrator yaratadi.")
    user = User(username=username, password_hash=hash_password(password), full_name=full_name,
                is_admin=first, language=language)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    if not first:
        from backend.security.services import apply_defaults
        await apply_defaults(user.id)
    return user
