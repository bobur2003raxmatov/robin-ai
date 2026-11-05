"""Dashboard API: Commands, Autopilot, Approvals, Emergency, Memory, Knowledge, Settings, Brain, Agents,
Devices, Telegram, Notifications, Reminders."""
from __future__ import annotations

import hashlib
import secrets
import shutil
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy import delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agents.devices import bridge
from backend.agents.events import hub
from backend.agents.executor import ToolContext, approvals, autopilot, run_command
from backend.agents.registry import TOOLS
from backend.agents.tools import run_computer
from backend.ai import prompts
from backend.ai.brain import get_brain
from backend.config import DATA_DIR
from backend.memory.database import (Approval, Command, Device, KnowledgeDoc, Notification, Reminder, Task, User,
                                     get_session, now)
from backend.memory.memory import Memory, extract_text
from backend.memory.settings_store import DEFAULTS, all_settings, set_setting
from backend.security.auth import current_user
from backend.security.permissions import audit, emergency
from backend.security.services import (SERVICES, allowed, denied_text, get_policy, locked_modules,
                                      require_service)

router = APIRouter(prefix="/api", tags=["robin"])


def _ctx(user: User, brain=None) -> ToolContext:
    return ToolContext(user_id=user.id, brain=brain, memory=Memory(user.id, brain.keys if brain else {}))


# ================================================================== COMMANDS
class CommandIn(BaseModel):
    name: str
    description: str = ""
    triggers: list[str] = []
    steps: list[dict] = []
    schedule: str = ""
    enabled: bool = True
    source: str = "manual"


def cmd_out(c: Command) -> dict:
    return {"id": c.id, "name": c.name, "description": c.description, "triggers": c.triggers, "steps": c.steps,
            "schedule": c.schedule, "enabled": c.enabled, "source": c.source, "run_count": c.run_count,
            "last_run": c.last_run.isoformat() if c.last_run else None}


@router.get("/commands", dependencies=[Depends(require_service("commands"))])
async def list_commands(user: User = Depends(current_user), db: AsyncSession = Depends(get_session)):
    rows = (await db.scalars(select(Command).where(Command.user_id == user.id).order_by(Command.name))).all()
    return [cmd_out(c) for c in rows]


@router.post("/commands", dependencies=[Depends(require_service("commands"))])
async def create_command(data: CommandIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_session)):
    name = data.name.strip()
    if not name:
        raise HTTPException(400, "Buyruq nomi kerak")
    if await db.scalar(select(Command).where(Command.user_id == user.id, Command.name == name)):
        raise HTTPException(409, "Bu nomli buyruq bor")
    for s in data.steps:
        if s.get("tool") not in TOOLS and s.get("tool") not in ("ai", "ask_robin"):
            raise HTTPException(400, f"Noma'lum asbob: {s.get('tool')}")
    c = Command(user_id=user.id, **data.model_dump() | {"name": name})
    db.add(c)
    await db.commit()
    await audit(user.id, "command_created", {"name": name}, actor="user")
    from backend.memory.notes import add_note
    steps = "\n".join(f"{i + 1}. `{s.get('tool')}` {s.get('note') or ''}" for i, s in enumerate(c.steps))
    body = (f"# {name}\n\n{c.description or ''}\n\n**Manba:** {c.source}  \n"
            f"**Ovozli iboralar:** {', '.join(c.triggers) or '—'}  \n**Jadval:** {c.schedule or '—'}\n\n"
            f"## Bosqichlar\n{steps}")
    await add_note(user.id, f"⚡ Yangi buyruq: {name}", body, "command")
    return cmd_out(c)


@router.put("/commands/{cid}", dependencies=[Depends(require_service("commands"))])
async def update_command(cid: str, data: CommandIn, user: User = Depends(current_user),
                         db: AsyncSession = Depends(get_session)):
    c = await db.get(Command, cid)
    if not c or c.user_id != user.id:
        raise HTTPException(404)
    for k, v in data.model_dump().items():
        setattr(c, k, v)
    await db.commit()
    return cmd_out(c)


@router.delete("/commands/{cid}", dependencies=[Depends(require_service("commands"))])
async def delete_command(cid: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_session)):
    await db.execute(delete(Command).where(Command.id == cid, Command.user_id == user.id))
    await db.commit()
    return {"ok": True}


@router.post("/commands/{cid}/run", dependencies=[Depends(require_service("commands"))])
async def run_cmd(cid: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_session)):
    c = await db.get(Command, cid)
    if not c or c.user_id != user.id:
        raise HTTPException(404)
    return await run_command(_ctx(user, await get_brain(user.id)), c)


@router.post("/commands/record/start", dependencies=[Depends(require_service("commands"))])
async def record_start(user: User = Depends(current_user)):
    """Smart add: start watching the owner's actions on the computer."""
    await hub.avatar(user.id, "listening", "Kuzatyapman…")
    return await run_computer(_ctx(user), "record_start")


class RecordStopIn(BaseModel):
    name: str = ""
    hint: str = ""     # owner's explanation of what they showed


@router.post("/commands/record/stop", dependencies=[Depends(require_service("commands"))])
async def record_stop(data: RecordStopIn, user: User = Depends(current_user)):
    """Stop recording and let AI turn the observed workflow into a reusable command (draft for review)."""
    rec = await run_computer(_ctx(user), "record_stop")
    events = rec.get("events", [])
    brain = await get_brain(user.id)
    draft = {"name": data.name or "Yangi buyruq", "description": data.hint, "triggers": [], "steps": [],
             "source": "recorded"}
    if brain.available and events:
        import json
        txt = json.dumps(events[-400:], ensure_ascii=False)[:30000]
        ai = await brain.ask_json(prompts.COMMAND_LEARN_PROMPT, f"Egasining izohi: {data.hint}\nTavsiya etilgan nom: "
                                  f"{data.name}\nMavjud asboblar: {', '.join(sorted(TOOLS))}\n\nHARAKATLAR:\n{txt}",
                                  fast=False, max_tokens=3000)
        draft.update({k: v for k, v in ai.items() if k in ("name", "description", "triggers", "steps") and v})
        if data.name:
            draft["name"] = data.name
        draft["steps"] = [s for s in draft["steps"] if s.get("tool") in TOOLS or s.get("tool") == "ai"]
    await hub.avatar(user.id, "happy", "O'rgandim!")
    return {"draft": draft, "events": len(events), "duration": rec.get("duration")}


class LearnTextIn(BaseModel):
    name: str
    description: str


@router.post("/commands/ai-create", dependencies=[Depends(require_service("commands"))])
async def ai_create(data: LearnTextIn, user: User = Depends(current_user)):
    """Describe a routine in words → ROBIN drafts the command steps."""
    brain = await get_brain(user.id)
    if not brain.available:
        raise HTTPException(400, "AI kaliti kerak")
    ai = await brain.ask_json(prompts.COMMAND_LEARN_PROMPT, f"Egasi ta'rifi: {data.description}\nNom: {data.name}\n"
                              f"Mavjud asboblar: {', '.join(sorted(TOOLS))}", fast=False, max_tokens=2500)
    ai["name"] = data.name or ai.get("name", "Yangi buyruq")
    ai["steps"] = [s for s in ai.get("steps", []) if s.get("tool") in TOOLS or s.get("tool") == "ai"]
    ai["source"] = "ai"
    return {"draft": ai}


@router.get("/tools")
async def list_tools(user: User = Depends(current_user)):
    return [{"name": t.name, "description": t.description, "risk": t.risk, "module": t.module,
             "parameters": t.parameters, "computer": t.computer} for t in sorted(TOOLS.values(), key=lambda x: x.name)]


# ================================================================== AUTOPILOT
class TaskIn(BaseModel):
    goal: str
    title: str = ""
    agent: str = "assistant"
    priority: int = 5
    background: bool = True


def task_out(t: Task) -> dict:
    return {"id": t.id, "title": t.title, "goal": t.goal, "status": t.status, "agent": t.agent, "plan": t.plan,
            "steps_log": t.steps_log[-50:], "result": t.result, "error": t.error, "review": t.review,
            "priority": t.priority, "created_at": t.created_at.isoformat(),
            "started_at": t.started_at.isoformat() if t.started_at else None,
            "finished_at": t.finished_at.isoformat() if t.finished_at else None}


@router.get("/tasks", dependencies=[Depends(require_service("autopilot"))])
async def tasks(status: str = "", user: User = Depends(current_user), db: AsyncSession = Depends(get_session)):
    stmt = select(Task).where(Task.user_id == user.id)
    if status:
        stmt = stmt.where(Task.status.in_(status.split(",")))
    rows = (await db.scalars(stmt.order_by(desc(Task.created_at)).limit(200))).all()
    return [task_out(t) for t in rows]


@router.post("/tasks", dependencies=[Depends(require_service("autopilot"))])
async def submit_task(data: TaskIn, user: User = Depends(current_user)):
    t = await autopilot.submit(user.id, data.title or data.goal[:80], data.goal, data.agent, data.priority,
                               data.background)
    return task_out(t)


@router.post("/tasks/{tid}/cancel", dependencies=[Depends(require_service("autopilot"))])
async def cancel_task(tid: str, user: User = Depends(current_user)):
    return {"ok": await autopilot.cancel(user.id, tid)}


@router.get("/autopilot", dependencies=[Depends(require_service("autopilot"))])
async def autopilot_dashboard(user: User = Depends(current_user), db: AsyncSession = Depends(get_session)):
    rows = (await db.scalars(select(Task).where(Task.user_id == user.id).order_by(desc(Task.created_at)).limit(300))).all()
    pend = (await db.scalars(select(Approval).where(Approval.user_id == user.id, Approval.status == "pending")
                             .order_by(desc(Approval.created_at)))).all()
    group = lambda *s: [task_out(t) for t in rows if t.status in s]
    agents = {}
    for t in rows:
        if t.status == "running":
            for s in t.plan or []:
                if s.get("status") == "running":
                    agents.setdefault(s["agent"], []).append({"task": t.title, "step": s["action"][:160]})
    return {"active": group("running", "waiting"), "queue": group("queued"), "completed": group("done")[:50],
            "failed": group("failed", "cancelled")[:50],
            "approvals": [{"id": a.id, "tool": a.tool, "args": a.args, "risk": a.risk, "reason": a.reason,
                           "task_id": a.task_id, "created_at": a.created_at.isoformat()} for a in pend],
            "agents": agents, "emergency": emergency.active(user.id)}


# ================================================================== APPROVALS & EMERGENCY
class DecisionIn(BaseModel):
    approved: bool


@router.get("/approvals")
async def list_approvals(user: User = Depends(current_user), db: AsyncSession = Depends(get_session)):
    rows = (await db.scalars(select(Approval).where(Approval.user_id == user.id)
                             .order_by(desc(Approval.created_at)).limit(100))).all()
    return [{"id": a.id, "tool": a.tool, "args": a.args, "risk": a.risk, "reason": a.reason, "status": a.status,
             "created_at": a.created_at.isoformat()} for a in rows]


@router.post("/approvals/{aid}")
async def decide(aid: str, data: DecisionIn, user: User = Depends(current_user)):
    if not await approvals.decide(user.id, aid, data.approved):
        raise HTTPException(404, "Tasdiq topilmadi yoki allaqachon hal qilingan")
    return {"ok": True}


@router.post("/emergency/stop")
async def emergency_stop(user: User = Depends(current_user)):
    emergency.trigger(user.id)
    n = await autopilot.cancel_all(user.id)
    for aid, fut in list(approvals.waiters.items()):
        if not fut.done():
            fut.set_result(False)
    await audit(user.id, "EMERGENCY_STOP", {"cancelled": n}, actor="owner")
    await hub.notify(user.id, "⛔ Favqulodda STOP", f"{n} ta vazifa to'xtatildi", "error")
    await hub.avatar(user.id, "warning", "To'xtadim")
    return {"stopped": True, "cancelled_tasks": n}


@router.post("/emergency/resume")
async def emergency_resume(user: User = Depends(current_user)):
    emergency.release(user.id)
    await audit(user.id, "EMERGENCY_RESUME", {}, actor="owner")
    return {"stopped": False}


# ================================================================== MEMORY & KNOWLEDGE
class MemoryIn(BaseModel):
    content: str
    kind: str = "fact"
    subject: str = ""
    importance: float = 0.6


@router.get("/memory", dependencies=[Depends(require_service("memory"))])
async def memory_list(kind: str = "", q: str = "", user: User = Depends(current_user)):
    rows = await Memory(user.id).list(kind or None, q)
    return [{"id": m.id, "kind": m.kind, "subject": m.subject, "content": m.content, "importance": m.importance,
             "links": m.links, "hits": m.hits, "updated_at": m.updated_at.isoformat()} for m in rows]


@router.post("/memory", dependencies=[Depends(require_service("memory"))])
async def memory_add(data: MemoryIn, user: User = Depends(current_user)):
    brain = await get_brain(user.id)
    return {"id": await Memory(user.id, brain.keys).remember(data.content, data.kind, data.subject, data.importance)}


@router.delete("/memory/{mid}", dependencies=[Depends(require_service("memory"))])
async def memory_delete(mid: int, user: User = Depends(current_user)):
    return {"ok": await Memory(user.id).forget(mid)}


@router.get("/memory/search", dependencies=[Depends(require_service("memory"))])
async def memory_search(q: str, user: User = Depends(current_user)):
    brain = await get_brain(user.id)
    m = Memory(user.id, brain.keys)
    items = await m.search(q)
    return {"memories": [{"id": i.id, "kind": i.kind, "subject": i.subject, "content": i.content} for i in items],
            "knowledge": await m.search_knowledge(q)}


@router.get("/memory/project/{name}", dependencies=[Depends(require_service("memory"))])
async def memory_project(name: str, user: User = Depends(current_user)):
    return {"context": await Memory(user.id).project_context(name)}


@router.post("/knowledge/upload", dependencies=[Depends(require_service("memory"))])
async def knowledge_upload(file: UploadFile = File(...), user: User = Depends(current_user)):
    folder = DATA_DIR / "files" / user.id
    folder.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch for ch in (file.filename or "file") if ch.isalnum() or ch in "._- ").strip() or "file"
    path = folder / f"{datetime.now():%Y%m%d%H%M%S}_{safe}"
    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    try:
        text = extract_text(str(path))
    except Exception as e:
        raise HTTPException(400, f"Faylni o'qib bo'lmadi: {e}") from e
    brain = await get_brain(user.id)
    doc = await Memory(user.id, brain.keys).add_document(safe, str(path), text, file.content_type or "",
                                                         path.stat().st_size)
    await audit(user.id, "knowledge_upload", {"name": safe, "chunks": doc.chunks}, actor="user")
    return {"id": doc.id, "name": doc.name, "chunks": doc.chunks, "path": str(path)}


@router.get("/knowledge", dependencies=[Depends(require_service("memory"))])
async def knowledge_list(user: User = Depends(current_user), db: AsyncSession = Depends(get_session)):
    rows = (await db.scalars(select(KnowledgeDoc).where(KnowledgeDoc.user_id == user.id)
                             .order_by(desc(KnowledgeDoc.created_at)))).all()
    return [{"id": d.id, "name": d.name, "path": d.path, "size": d.size, "chunks": d.chunks,
             "created_at": d.created_at.isoformat()} for d in rows]


@router.delete("/knowledge/{did}", dependencies=[Depends(require_service("memory"))])
async def knowledge_delete(did: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_session)):
    from backend.memory.database import KnowledgeChunk
    await db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.doc_id == did, KnowledgeChunk.user_id == user.id))
    await db.execute(delete(KnowledgeDoc).where(KnowledgeDoc.id == did, KnowledgeDoc.user_id == user.id))
    await db.commit()
    return {"ok": True}


# ================================================================== SETTINGS / BRAIN / AGENTS
@router.get("/settings")
async def get_settings(user: User = Depends(current_user)):
    out = await all_settings(user.id)
    pol = await get_policy(user.id)
    out["policy"] = {"services": pol["services"], "limits": pol["limits"], "locked_modules": sorted(locked_modules(pol)),
                     "catalog": {k: {"title": v["title"], "desc": v["desc"]} for k, v in SERVICES.items()}}
    return out


@router.put("/settings/{key}")
async def put_settings(key: str, value: dict, user: User = Depends(current_user)):
    if key not in DEFAULTS and key != "api_keys":
        raise HTTPException(404, "Noma'lum bo'lim")
    if key in ("api_keys", "brain") and not await allowed(user.id, "own_keys"):
        raise HTTPException(403, denied_text("own_keys"))
    if key == "brain":           # "Gemini" typed into a model field is not a model id → keep automatic
        from backend.ai.providers import valid_model_name
        value = {k: (valid_model_name(v) if k.endswith("_model") and isinstance(v, str) else v) for k, v in value.items()}
    if key == "permissions":     # modules locked by the admin stay as the user had them (and stay off)
        locked = locked_modules(await get_policy(user.id))
        value = {k: v for k, v in value.items() if k not in locked}
    res = await set_setting(user.id, key, value)
    await audit(user.id, "settings_changed", {"key": key, "fields": list(value)}, actor="user")
    await hub.emit(user.id, "settings_changed", {"key": key})
    if key == "api_keys":
        return {"ok": True}
    return res


@router.get("/brain/status")
async def brain_status(user: User = Depends(current_user)):
    return (await get_brain(user.id)).status()


@router.post("/brain/test")
async def brain_test(user: User = Depends(current_user)):
    import time
    from backend.agents.executor import provider_error_message
    brain = await get_brain(user.id)

    async def one(name, prov):
        t = time.time()
        try:
            r = await prov.chat("Qisqa javob ber.", [{"role": "user", "content": "Salom! Bir so'z bilan javob ber."}],
                                max_tokens=30)
            return name, {"ok": True, "reply": r.text.strip()[:80], "model": r.model, "configured": getattr(prov, "_configured", prov.model),
                          "fallback": r.model != getattr(prov, "_configured", prov.model),
                          "seconds": round(time.time() - t, 1)}
        except Exception as e:
            return name, {"ok": False, "error": str(e)[:600], "hint": provider_error_message(str(e)),
                          "seconds": round(time.time() - t, 1)}
    import asyncio
    return dict(await asyncio.gather(*[one(n, p) for n, p in brain.providers.items()]))


@router.get("/agents")
async def agents(user: User = Depends(current_user)):
    return [{"id": k, "title": v["title"], "prompt": v["prompt"]} for k, v in prompts.SPECIALISTS.items()]


# ================================================================== DEVICES (all laptops)
class DeviceIn(BaseModel):
    name: str


@router.post("/devices", dependencies=[Depends(require_service("devices"))])
async def create_device(data: DeviceIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_session)):
    token = secrets.token_urlsafe(32)
    d = Device(user_id=user.id, name=data.name, token_hash=hashlib.sha256(token.encode()).hexdigest())
    db.add(d)
    await db.commit()
    return {"id": d.id, "name": d.name, "device_token": f"{d.id}.{token}",
            "hint": "desktop/robin_agent.py --server URL --token <device_token>"}


@router.get("/devices", dependencies=[Depends(require_service("devices"))])
async def list_devices(user: User = Depends(current_user), db: AsyncSession = Depends(get_session)):
    rows = (await db.scalars(select(Device).where(Device.user_id == user.id))).all()
    online = {d["id"] for d in bridge.online(user.id)}
    return [{"id": d.id, "name": d.name, "platform": d.platform, "online": d.id in online,
             "last_seen": d.last_seen.isoformat() if d.last_seen else None} for d in rows]


@router.delete("/devices/{did}", dependencies=[Depends(require_service("devices"))])
async def delete_device(did: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_session)):
    await db.execute(delete(Device).where(Device.id == did, Device.user_id == user.id))
    await db.commit()
    return {"ok": True}


device_ws = APIRouter()


@device_ws.websocket("/ws/device")
async def device_socket(ws: WebSocket):
    from backend.memory.database import SessionLocal
    raw = ws.query_params.get("token", "")
    did, _, secret = raw.partition(".")
    async with SessionLocal() as db:
        d = await db.get(Device, did)
        valid = d and secrets.compare_digest(d.token_hash, hashlib.sha256(secret.encode()).hexdigest())
        if valid:
            d.last_seen = now()
            d.platform = ws.query_params.get("platform", "")[:60]
            await db.commit()
    await ws.accept()
    if not valid:
        await ws.send_json({"type": "error", "error": "unauthorized"})
        await ws.close()
        return
    if not await allowed(d.user_id, "devices"):
        await ws.send_json({"type": "error", "error": denied_text("devices")})
        await ws.close()
        return
    bridge.register(d.user_id, d.id, ws, {"name": d.name, "platform": d.platform})
    await hub.notify(d.user_id, f"💻 Qurilma ulandi: {d.name}", "", "success", external=False)
    try:
        while True:
            msg = await ws.receive_json()
            if msg.get("type") == "result":
                bridge.resolve(msg)
            elif msg.get("type") == "chat":   # desktop widget voice/text command
                from backend.agents.executor import chat
                import asyncio

                async def run(m=msg):
                    res = await chat(d.user_id, m.get("text", ""), m.get("conversation_id"), bool(m.get("voice")),
                                     channel="desktop", device_id=d.id)
                    await ws.send_json({"type": "chat_reply", **res})
                asyncio.create_task(run())
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        bridge.unregister(d.user_id, d.id)


# ================================================================== TELEGRAM / NOTIFICATIONS / REMINDERS
@router.post("/telegram/link-code", dependencies=[Depends(require_service("telegram"))])
async def telegram_code(user: User = Depends(current_user)):
    from backend.integrations.telegram_bot import _bot, new_link_code
    code = await new_link_code(user.id)
    return {"code": code, "bot_running": _bot is not None, "instruction": f"Telegram botga yuboring: /link {code}"}


@router.get("/notifications")
async def notifications(user: User = Depends(current_user), db: AsyncSession = Depends(get_session)):
    rows = (await db.scalars(select(Notification).where(Notification.user_id == user.id)
                             .order_by(desc(Notification.id)).limit(100))).all()
    unread = await db.scalar(select(func.count()).select_from(Notification).where(
        Notification.user_id == user.id, Notification.read.is_(False)))
    return {"unread": unread, "items": [{"id": n.id, "level": n.level, "title": n.title, "body": n.body,
                                         "read": n.read, "created_at": n.created_at.isoformat()} for n in rows]}


@router.post("/notifications/read")
async def notifications_read(user: User = Depends(current_user), db: AsyncSession = Depends(get_session)):
    for n in (await db.scalars(select(Notification).where(Notification.user_id == user.id,
                                                          Notification.read.is_(False)))).all():
        n.read = True
    await db.commit()
    return {"ok": True}


class ReminderIn(BaseModel):
    title: str
    due_at: str
    note: str = ""
    kind: str = "reminder"
    repeat: str = ""


@router.get("/reminders", dependencies=[Depends(require_service("reminders"))])
async def reminders(user: User = Depends(current_user), db: AsyncSession = Depends(get_session)):
    rows = (await db.scalars(select(Reminder).where(Reminder.user_id == user.id, Reminder.done.is_(False))
                             .order_by(Reminder.due_at))).all()
    return [{"id": r.id, "title": r.title, "note": r.note, "kind": r.kind, "repeat": r.repeat,
             "due_at": r.due_at.isoformat(), "notified": r.notified} for r in rows]


@router.post("/reminders", dependencies=[Depends(require_service("reminders"))])
async def add_reminder(data: ReminderIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_session)):
    dt = datetime.fromisoformat(data.due_at.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.astimezone()
    r = Reminder(user_id=user.id, title=data.title, note=data.note, kind=data.kind, repeat=data.repeat,
                 due_at=dt.astimezone(timezone.utc))
    db.add(r)
    await db.commit()
    return {"id": r.id}


@router.delete("/reminders/{rid}", dependencies=[Depends(require_service("reminders"))])
async def del_reminder(rid: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_session)):
    r = await db.get(Reminder, rid)
    if r and r.user_id == user.id:
        r.done = True
        await db.commit()
    return {"ok": True}
