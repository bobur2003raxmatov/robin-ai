from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.memory.database import User, get_session
from backend.security.auth import (create_token, current_user, hash_password, register_user,
                                   verify_password)
from backend.security.permissions import audit

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterIn(BaseModel):
    username: str
    password: str
    full_name: str = ""
    language: str = "uz"


class LoginIn(BaseModel):
    username: str
    password: str


class PasswordIn(BaseModel):
    old_password: str
    new_password: str


def user_out(u: User) -> dict:
    return {"id": u.id, "username": u.username, "full_name": u.full_name, "is_admin": u.is_admin,
            "language": u.language, "created_at": u.created_at.isoformat()}


@router.post("/register")
async def register(data: RegisterIn, db: AsyncSession = Depends(get_session)):
    u = await register_user(db, data.username, data.password, data.full_name, data.language)
    await audit(u.id, "register", {"username": u.username}, actor="user")
    return {"token": create_token(u.id), "user": user_out(u)}


_fails: dict[str, list[float]] = {}
MAX_FAILS, WINDOW = 5, 600     # 5 wrong passwords → 10 minute lock (per login + IP)


@router.get("/config")
async def auth_config():
    from backend.security.services import load_config
    return {"registration_open": load_config()["registration_open"]}


@router.post("/login")
async def login(data: LoginIn, request: Request, db: AsyncSession = Depends(get_session)):
    import time
    name = data.username.strip().lower()
    key = f"{name}|{request.client.host if request.client else ''}"
    now_t = time.time()
    recent = [t for t in _fails.get(key, []) if now_t - t < WINDOW]
    if len(recent) >= MAX_FAILS:
        raise HTTPException(429, f"Juda ko'p noto'g'ri urinish. {int((WINDOW - (now_t - recent[0])) // 60) + 1} daqiqadan keyin qayta urining.")
    u = await db.scalar(select(User).where(User.username == name))
    if not u or not verify_password(data.password, u.password_hash):
        _fails[key] = recent + [now_t]
        if u:
            await audit(u.id, "login_failed", {"ip": key.split("|")[1]}, ok=False, actor="user")
        raise HTTPException(401, "Login yoki parol noto'g'ri")
    if not u.is_active:
        raise HTTPException(403, "Hisobingiz administrator tomonidan bloklangan")
    _fails.pop(key, None)
    await audit(u.id, "login", {"ip": key.split("|")[1]}, actor="user")
    return {"token": create_token(u.id), "user": user_out(u)}


@router.get("/me")
async def me(user: User = Depends(current_user)):
    return user_out(user)


@router.post("/password")
async def change_password(data: PasswordIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_session)):
    u = await db.get(User, user.id)
    if not verify_password(data.old_password, u.password_hash):
        raise HTTPException(400, "Eski parol noto'g'ri")
    if len(data.new_password) < 8:
        raise HTTPException(400, "Yangi parol kamida 8 belgi")
    u.password_hash = hash_password(data.new_password)
    await db.commit()
    await audit(u.id, "password_changed", {}, actor="user")
    return {"ok": True}
