"""System API: resource monitor, activity/audit log, error log + self-repair, backups, admin user management."""
from __future__ import annotations

import asyncio
import shutil
from datetime import datetime

import psutil
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agents.executor import diagnose_errors
from backend.config import DATA_DIR, settings
from backend.memory.database import AuditLog, ErrorLog, User, get_session
from backend.security.auth import admin_user, current_user
from backend.security.permissions import audit, emergency

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/health")
async def health():
    return {"ok": True, "name": settings.APP_NAME, "version": settings.VERSION, "time": datetime.now().isoformat()}


@router.get("/resources")
async def resources(user: User = Depends(current_user)):
    def snap():
        vm = psutil.virtual_memory()
        net = psutil.net_io_counters()
        return {"cpu": psutil.cpu_percent(interval=0.3), "ram": vm.percent, "ram_used_gb": round(vm.used / 1e9, 2),
                "ram_total_gb": round(vm.total / 1e9, 2), "net_sent_mb": round(net.bytes_sent / 1e6, 1),
                "net_recv_mb": round(net.bytes_recv / 1e6, 1),
                "robin_ram_mb": round(psutil.Process().memory_info().rss / 1e6, 1)}
    return await asyncio.to_thread(snap)


@router.get("/status")
async def status(user: User = Depends(current_user), db: AsyncSession = Depends(get_session)):
    """Live health of every ROBIN subsystem in percent (Settings → Ishlash holati)."""
    import time as _t
    from datetime import timedelta, timezone

    from sqlalchemy import func, text

    from backend.agents import scheduler
    from backend.agents.devices import bridge
    from backend.ai.brain import get_brain
    from backend.integrations import telegram_bot
    from backend.memory.database import Message, Task

    since = datetime.now(timezone.utc) - timedelta(hours=24)
    t0 = _t.time()
    await db.execute(text("select 1"))
    db_ms = round((_t.time() - t0) * 1000, 1)

    async def pct(ok_q, total_q):
        total = await db.scalar(total_q) or 0
        ok = await db.scalar(ok_q) or 0
        return (round(ok / total * 100, 1) if total else None), total

    tool_base = select(func.count()).select_from(AuditLog).where(
        AuditLog.user_id == user.id, AuditLog.created_at >= since, AuditLog.action.like("tool:%"))
    tools_pct, tools_n = await pct(tool_base.where(AuditLog.ok.is_(True)), tool_base)
    msg_base = select(func.count()).select_from(Message).where(
        Message.user_id == user.id, Message.role == "assistant", Message.created_at >= since)
    from sqlalchemy import String, cast
    chat_err = await db.scalar(msg_base.where(cast(Message.meta, String).like('%"error"%'))) or 0
    chat_n = await db.scalar(msg_base) or 0
    chat_pct = round((chat_n - chat_err) / chat_n * 100, 1) if chat_n else None
    task_base = select(func.count()).select_from(Task).where(
        Task.user_id == user.id, Task.created_at >= since, Task.status.in_(["done", "failed"]))
    task_pct, task_n = await pct(task_base.where(Task.status == "done"), task_base)

    brain = await get_brain(user.id)
    st = brain.status()["providers"]
    providers = {n: {"title": p["title"], "connected": p["connected"], "model": p["model"], **p["health"]}
                 for n, p in st.items() if p["connected"]}
    rated = [p["success_pct"] for p in providers.values() if p.get("success_pct") is not None]
    ai_pct = (max(rated) if rated else 100.0) if providers else 0.0   # healthy if at least one provider works
    sched_age = _t.time() - scheduler.STATE["last_tick"] if scheduler.STATE["last_tick"] else None
    components = [
        {"id": "db", "name": "Ma'lumotlar bazasi", "pct": 100.0 if db_ms < 500 else 60.0, "detail": f"{db_ms} ms"},
        {"id": "ai", "name": "AI miya", "pct": ai_pct,
         "detail": f"{len(providers)} ta provayder ulangan" if providers else "AI kaliti yo'q"},
        {"id": "scheduler", "name": "Rejalashtiruvchi (eslatmalar)",
         "pct": 100.0 if sched_age is not None and sched_age < 90 else 0.0,
         "detail": f"{int(sched_age)} s oldin" if sched_age is not None else "ishga tushmagan"},
        {"id": "computer", "name": "Kompyuter boshqaruvi",
         "pct": 100.0 if (settings.LOCAL_EXECUTION or bridge.online(user.id)) else 0.0,
         "detail": "lokal" if settings.LOCAL_EXECUTION else f"{len(bridge.online(user.id))} qurilma"},
        {"id": "telegram", "name": "Telegram", "pct": 100.0 if telegram_bot._bot else None,
         "detail": "ishlayapti" if telegram_bot._bot else "token kiritilmagan"},
    ]
    metrics = [
        {"id": "chat", "name": "Chat javoblari", "pct": chat_pct, "n": chat_n},
        {"id": "tools", "name": "Asboblar (buyruqlar)", "pct": tools_pct, "n": tools_n},
        {"id": "tasks", "name": "Autopilot vazifalari", "pct": task_pct, "n": task_n},
    ]
    vals = [c["pct"] for c in components if c["pct"] is not None] + [m["pct"] for m in metrics if m["pct"] is not None]
    overall = round(sum(vals) / len(vals), 1) if vals else 0.0
    res = await resources(user)
    return {"overall": overall, "components": components, "metrics": metrics, "providers": providers,
            "resources": res, "uptime_s": int(_t.time() - scheduler.STATE["started"]), "time": datetime.now().isoformat()}


@router.get("/activity")
async def activity(limit: int = 200, user: User = Depends(current_user), db: AsyncSession = Depends(get_session)):
    rows = (await db.scalars(select(AuditLog).where(AuditLog.user_id == user.id)
                             .order_by(desc(AuditLog.id)).limit(min(limit, 1000)))).all()
    return [{"id": a.id, "actor": a.actor, "action": a.action, "detail": a.detail, "ok": a.ok,
             "at": a.created_at.isoformat()} for a in rows]


@router.get("/errors")
async def errors(user: User = Depends(current_user), db: AsyncSession = Depends(get_session)):
    stmt = select(ErrorLog).order_by(desc(ErrorLog.id)).limit(100)
    if not user.is_admin:
        stmt = stmt.where(ErrorLog.user_id == user.id)
    rows = (await db.scalars(stmt)).all()
    return [{"id": e.id, "where": e.where, "error": e.error, "diagnosis": e.diagnosis, "fix_proposal": e.fix_proposal,
             "resolved": e.resolved, "at": e.created_at.isoformat()} for e in rows]


@router.post("/self-repair")
async def self_repair(user: User = Depends(admin_user)):
    """ROBIN analyses its own errors and proposes fixes; admin reviews & applies."""
    return await diagnose_errors(user.id)


@router.post("/errors/{eid}/resolve")
async def resolve(eid: int, user: User = Depends(admin_user), db: AsyncSession = Depends(get_session)):
    e = await db.get(ErrorLog, eid)
    if e:
        e.resolved = True
        await db.commit()
    return {"ok": True}


@router.post("/backup")
async def backup(user: User = Depends(admin_user)):
    if not settings.DATABASE_URL.startswith("sqlite"):
        raise HTTPException(400, "PostgreSQL uchun pg_dump ishlating")
    src = DATA_DIR / "robin.db"
    dst = DATA_DIR / "backups" / f"robin_{datetime.now():%Y%m%d_%H%M%S}.db"
    await asyncio.to_thread(shutil.copy2, src, dst)
    await audit(user.id, "backup", {"file": dst.name}, actor="admin")
    return {"file": dst.name, "size": dst.stat().st_size}


@router.get("/backups")
async def backups(user: User = Depends(admin_user)):
    return sorted([{"file": p.name, "size": p.stat().st_size} for p in (DATA_DIR / "backups").glob("*.db")],
                  key=lambda x: x["file"], reverse=True)


@router.get("/backups/{name}")
async def download_backup(name: str, user: User = Depends(admin_user)):
    p = (DATA_DIR / "backups" / name).resolve()
    if p.parent != (DATA_DIR / "backups").resolve() or not p.exists():
        raise HTTPException(404)
    return FileResponse(p, filename=name)


@router.get("/users")
async def users(user: User = Depends(admin_user), db: AsyncSession = Depends(get_session)):
    rows = (await db.scalars(select(User).order_by(User.created_at))).all()
    return [{"id": u.id, "username": u.username, "full_name": u.full_name, "is_admin": u.is_admin,
             "is_active": u.is_active, "created_at": u.created_at.isoformat()} for u in rows]


@router.post("/users/{uid}/toggle")
async def toggle_user(uid: str, user: User = Depends(admin_user), db: AsyncSession = Depends(get_session)):
    u = await db.get(User, uid)
    if not u or u.id == user.id:
        raise HTTPException(400)
    u.is_active = not u.is_active
    await db.commit()
    return {"is_active": u.is_active}


@router.post("/global-stop")
async def global_stop(user: User = Depends(admin_user)):
    from backend.agents.executor import autopilot
    emergency.trigger(None)
    n = await autopilot.cancel_all(None)
    await audit(user.id, "GLOBAL_EMERGENCY_STOP", {"cancelled": n}, actor="admin")
    return {"stopped": True, "cancelled": n}


@router.post("/global-resume")
async def global_resume(user: User = Depends(admin_user)):
    emergency.release(None)
    return {"stopped": False}
