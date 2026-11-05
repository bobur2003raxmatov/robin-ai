"""Admin Panel API: users (create, edit, block, reset password, end sessions, stop agents), per-user service access,
daily limits, usage statistics, per-user activity, registration control and defaults for new users."""
from __future__ import annotations

import secrets
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.memory.database import AuditLog, Device, ErrorLog, Message, TelegramLink, User, get_session
from backend.security.auth import admin_user, hash_password, register_user
from backend.security.permissions import audit, emergency
from backend.security.services import (LIMITS, SERVICES, get_policy, load_config, save_config, set_policy,
                                       usage_today)

router = APIRouter(prefix="/api/admin", tags=["admin"])


class NewUser(BaseModel):
    username: str
    password: str = ""
    full_name: str = ""
    is_admin: bool = False
    language: str = "uz"
    services: dict[str, bool] | None = None
    limits: dict[str, int] | None = None


class EditUser(BaseModel):
    full_name: str | None = None
    is_admin: bool | None = None
    is_active: bool | None = None


class PolicyIn(BaseModel):
    services: dict[str, bool] | None = None
    limits: dict[str, int] | None = None
    note: str | None = None


class BulkIn(BaseModel):
    user_ids: list[str]
    services: dict[str, bool] = {}
    limits: dict[str, int] | None = None


class PasswordIn(BaseModel):
    password: str = ""     # empty → generate a strong one


def _iso(dt: datetime | None) -> str | None:
    if not dt:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat()


def _since(days: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


async def _admins(db: AsyncSession) -> int:
    return await db.scalar(select(func.count()).select_from(User).where(User.is_admin.is_(True), User.is_active.is_(True))) or 0


async def _get(db: AsyncSession, uid: str) -> User:
    u = await db.get(User, uid)
    if not u:
        raise HTTPException(404, "Foydalanuvchi topilmadi")
    return u


@router.get("/catalog")
async def catalog(admin: User = Depends(admin_user)):
    return {"services": {k: {"title": v["title"], "desc": v["desc"], "modules": v["modules"]} for k, v in SERVICES.items()},
            "limits": {"daily_messages": "Kunlik xabarlar (0 = cheksiz)", "daily_voice": "Kunlik ovozli so'rovlar (0 = cheksiz)"}}


@router.get("/overview")
async def overview(admin: User = Depends(admin_user), db: AsyncSession = Depends(get_session)):
    day, week = _since(1), _since(7)
    users = await db.scalar(select(func.count()).select_from(User)) or 0
    active_users = await db.scalar(select(func.count()).select_from(User).where(User.is_active.is_(True))) or 0
    um = select(func.count()).select_from(Message).where(Message.role == "user")
    msgs_day = await db.scalar(um.where(Message.created_at >= day)) or 0
    msgs_week = await db.scalar(um.where(Message.created_at >= week)) or 0
    active_day = await db.scalar(select(func.count(func.distinct(Message.user_id))).where(
        Message.role == "user", Message.created_at >= day)) or 0
    tools_day = await db.scalar(select(func.count()).select_from(AuditLog).where(
        AuditLog.action.like("tool:%"), AuditLog.created_at >= day)) or 0
    blocked_day = await db.scalar(select(func.count()).select_from(AuditLog).where(
        AuditLog.action.like("blocked:%"), AuditLog.created_at >= day)) or 0
    failed_logins = await db.scalar(select(func.count()).select_from(AuditLog).where(
        AuditLog.action == "login_failed", AuditLog.created_at >= day)) or 0
    open_errors = await db.scalar(select(func.count()).select_from(ErrorLog).where(ErrorLog.resolved.is_(False))) or 0
    # messages per day for the last 14 days (all users)
    rows = (await db.execute(select(Message.created_at).where(Message.role == "user", Message.created_at >= _since(14))))
    per_day: dict[str, int] = {}
    for (ts,) in rows:
        k = (ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)).astimezone().strftime("%m-%d")
        per_day[k] = per_day.get(k, 0) + 1
    days = [(datetime.now() - timedelta(days=i)).strftime("%m-%d") for i in range(13, -1, -1)]
    return {"users": users, "active_users": active_users, "active_today": active_day, "messages_today": msgs_day,
            "messages_week": msgs_week, "tools_today": tools_day, "blocked_today": blocked_day,
            "failed_logins_today": failed_logins, "open_errors": open_errors,
            "chart": [{"day": d, "n": per_day.get(d, 0)} for d in days],
            "global_stop": emergency.global_stop, "config": load_config()}


@router.get("/users")
async def users(admin: User = Depends(admin_user), db: AsyncSession = Depends(get_session)):
    rows = (await db.scalars(select(User).order_by(User.created_at))).all()
    week = _since(7)
    total = dict((await db.execute(select(Message.user_id, func.count()).where(Message.role == "user")
                                   .group_by(Message.user_id))).all())
    wk = dict((await db.execute(select(Message.user_id, func.count()).where(Message.role == "user", Message.created_at >= week)
                                .group_by(Message.user_id))).all())
    last = dict((await db.execute(select(AuditLog.user_id, func.max(AuditLog.created_at)).group_by(AuditLog.user_id))).all())
    last_msg = dict((await db.execute(select(Message.user_id, func.max(Message.created_at)).group_by(Message.user_id))).all())
    devs = dict((await db.execute(select(Device.user_id, func.count()).group_by(Device.user_id))).all())
    tg = dict((await db.execute(select(TelegramLink.user_id, func.count()).where(TelegramLink.chat_id != "")
                                .group_by(TelegramLink.user_id))).all())
    out = []
    for u in rows:
        pol = await get_policy(u.id)
        la = max([x for x in (last.get(u.id), last_msg.get(u.id)) if x], default=None)
        out.append({"id": u.id, "username": u.username, "full_name": u.full_name, "is_admin": u.is_admin,
                    "is_active": u.is_active, "language": u.language, "created_at": _iso(u.created_at),
                    "last_active": _iso(la), "messages_total": total.get(u.id, 0),
                    "messages_week": wk.get(u.id, 0), "today": await usage_today(u.id),
                    "devices": devs.get(u.id, 0), "telegram": bool(tg.get(u.id)),
                    "stopped": u.id in emergency.users, "services": pol["services"], "limits": pol["limits"],
                    "note": pol["note"], "is_self": u.id == admin.id})
    return out


@router.post("/users")
async def create_user(data: NewUser, admin: User = Depends(admin_user), db: AsyncSession = Depends(get_session)):
    pw = data.password or secrets.token_urlsafe(9)
    u = await register_user(db, data.username, pw, data.full_name, data.language, by_admin=True)
    if data.is_admin:
        u.is_admin = True
        await db.commit()
    if data.services or data.limits:
        await set_policy(u.id, data.services, data.limits)
    await audit(admin.id, "admin:user_created", {"username": u.username, "is_admin": data.is_admin}, actor="admin")
    return {"id": u.id, "username": u.username, "password": pw if not data.password else None}


@router.put("/users/{uid}")
async def edit_user(uid: str, data: EditUser, admin: User = Depends(admin_user), db: AsyncSession = Depends(get_session)):
    u = await _get(db, uid)
    if u.id == admin.id and (data.is_admin is False or data.is_active is False):
        raise HTTPException(400, "O'zingizni bloklay yoki admin huquqidan mahrum qila olmaysiz")
    if u.is_admin and (data.is_admin is False or data.is_active is False) and await _admins(db) <= 1:
        raise HTTPException(400, "Kamida bitta faol admin qolishi kerak")
    changed = {}
    for f in ("full_name", "is_admin", "is_active"):
        v = getattr(data, f)
        if v is not None and getattr(u, f) != v:
            setattr(u, f, v)
            changed[f] = v
    await db.commit()
    from backend.security import services
    services._cache.pop(uid, None)
    if data.is_active is False:          # blocked → stop agents, end sessions immediately
        emergency.trigger(uid)
        from backend.agents.executor import autopilot
        await autopilot.cancel_all(uid)
        await set_policy(uid, tokens_after=time.time())
    elif data.is_active is True:
        emergency.release(uid)
    await audit(admin.id, "admin:user_edited", {"user": u.username, **changed}, actor="admin")
    return {"ok": True, **changed}


@router.post("/users/{uid}/password")
async def reset_password(uid: str, data: PasswordIn, admin: User = Depends(admin_user),
                         db: AsyncSession = Depends(get_session)):
    u = await _get(db, uid)
    pw = data.password or secrets.token_urlsafe(9)
    if len(pw) < 8:
        raise HTTPException(400, "Parol kamida 8 belgi")
    u.password_hash = hash_password(pw)
    await db.commit()
    if u.id != admin.id:
        await set_policy(uid, tokens_after=time.time())     # old sessions are no longer valid
    await audit(admin.id, "admin:password_reset", {"user": u.username}, actor="admin")
    return {"ok": True, "password": pw}


@router.post("/users/{uid}/logout")
async def end_sessions(uid: str, admin: User = Depends(admin_user), db: AsyncSession = Depends(get_session)):
    u = await _get(db, uid)
    if u.id == admin.id:
        raise HTTPException(400, "O'z sessiyangizni bu yerdan yakunlay olmaysiz")
    await set_policy(uid, tokens_after=time.time())
    await audit(admin.id, "admin:sessions_ended", {"user": u.username}, actor="admin")
    return {"ok": True}


@router.post("/users/{uid}/stop")
async def stop_user(uid: str, admin: User = Depends(admin_user), db: AsyncSession = Depends(get_session)):
    u = await _get(db, uid)
    from backend.agents.executor import autopilot
    if uid in emergency.users:
        emergency.release(uid)
        await audit(admin.id, "admin:user_resumed", {"user": u.username}, actor="admin")
        return {"stopped": False}
    emergency.trigger(uid)
    n = await autopilot.cancel_all(uid)
    await audit(admin.id, "admin:user_stopped", {"user": u.username, "cancelled": n}, actor="admin")
    return {"stopped": True, "cancelled": n}


@router.get("/users/{uid}/policy")
async def get_user_policy(uid: str, admin: User = Depends(admin_user)):
    return await get_policy(uid)


@router.put("/users/{uid}/policy")
async def put_user_policy(uid: str, data: PolicyIn, admin: User = Depends(admin_user),
                          db: AsyncSession = Depends(get_session)):
    u = await _get(db, uid)
    pol = await set_policy(uid, data.services, data.limits, data.note)
    off = [k for k, v in (data.services or {}).items() if not v]
    await audit(admin.id, "admin:policy_changed", {"user": u.username, "disabled": ",".join(off),
                                                   "limits": str(data.limits or {})}, actor="admin")
    from backend.agents.events import hub
    await hub.emit(uid, "policy_changed", {})
    return pol


@router.put("/policy/bulk")
async def bulk_policy(data: BulkIn, admin: User = Depends(admin_user)):
    from backend.agents.events import hub
    for uid in data.user_ids:
        await set_policy(uid, data.services, data.limits)
        await hub.emit(uid, "policy_changed", {})
    await audit(admin.id, "admin:policy_bulk", {"users": len(data.user_ids), "services": str(data.services)}, actor="admin")
    return {"ok": True, "n": len(data.user_ids)}


@router.get("/users/{uid}/activity")
async def user_activity(uid: str, limit: int = 150, admin: User = Depends(admin_user),
                        db: AsyncSession = Depends(get_session)):
    rows = (await db.scalars(select(AuditLog).where(AuditLog.user_id == uid).order_by(desc(AuditLog.id))
                             .limit(min(limit, 500)))).all()
    return [{"actor": a.actor, "action": a.action, "detail": a.detail, "ok": a.ok, "at": _iso(a.created_at)}
            for a in rows]


@router.get("/config")
async def get_config(admin: User = Depends(admin_user)):
    return load_config()


@router.put("/config")
async def put_config(data: dict, admin: User = Depends(admin_user)):
    cfg = save_config(data)
    await audit(admin.id, "admin:config_changed", {"registration_open": cfg["registration_open"]}, actor="admin")
    return cfg


@router.get("/audit")
async def global_audit(limit: int = 200, action: str = "", admin: User = Depends(admin_user),
                       db: AsyncSession = Depends(get_session)):
    """Audit across all users (admin actions, logins, blocked actions…)."""
    stmt = select(AuditLog, User.username).join(User, User.id == AuditLog.user_id, isouter=True)
    if action:
        stmt = stmt.where(AuditLog.action.like(f"%{action}%"))
    rows = (await db.execute(stmt.order_by(desc(AuditLog.id)).limit(min(limit, 1000)))).all()
    return [{"user": name or a.user_id, "actor": a.actor, "action": a.action, "detail": a.detail, "ok": a.ok,
             "at": _iso(a.created_at)} for a, name in rows]


__all__ = ["router", "LIMITS"]
