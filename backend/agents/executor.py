"""ROBIN Executor — the agent engine.

    Qabul qiladi → Ma'nosini tushunadi → Reja tuzadi → Bajaradi → Tekshiradi → Topshiradi

* run_agent        : tool-using loop of one specialist agent (Multi-Brain)
* execute_tool     : Action Validator → Approval Center → Audit Log → run → Error intelligence
* ApprovalCenter   : waits for the owner's decision on risky actions
* Autopilot        : task queue, parallel workers, plan → steps → synthesis → self-review
* chat()           : entry point for Chat / Voice / Telegram messages
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import traceback
from datetime import datetime, timezone

from sqlalchemy import select

from backend.agents import tools as _tools  # noqa: F401  (registers tools)
from backend.agents.events import fire, hub
from backend.agents.registry import TOOLS, ToolContext, tools_for
from backend.ai import prompts
from backend.ai.brain import Brain, NoProviderError, get_brain, parse_json
from backend.ai.planner import make_plan, ready_steps
from backend.ai.providers import ProviderError
from backend.config import settings
from backend.memory.database import (Approval, Command, Conversation, ErrorLog, Feedback, SessionLocal, Task,
                                     User, now)
from backend.memory.memory import Memory
from backend.memory.settings_store import get_setting, set_setting
from backend.security.permissions import audit, emergency, validate

log = logging.getLogger("robin.executor")


class StopRequested(Exception):
    pass


# =================================================================== APPROVAL CENTER
class ApprovalCenter:
    def __init__(self) -> None:
        self.waiters: dict[str, asyncio.Future] = {}

    async def request(self, ctx: ToolContext, tool: str, args: dict, risk: str, reason: str,
                      timeout: float = 900) -> bool:
        async with SessionLocal() as db:
            ap = Approval(user_id=ctx.user_id, task_id=ctx.task_id, tool=tool, args=_safe_args(args), risk=risk,
                          reason=reason)
            db.add(ap)
            await db.commit()
        fut = asyncio.get_running_loop().create_future()
        self.waiters[ap.id] = fut
        payload = {"id": ap.id, "tool": tool, "args": ap.args, "risk": risk, "reason": reason, "task_id": ctx.task_id}
        await hub.emit(ctx.user_id, "approval_request", payload)
        await hub.notify(ctx.user_id, f"Tasdiq kerak: {tool} ({risk})", reason or json.dumps(ap.args, ensure_ascii=False)[:500],
                         "warning")
        from backend.integrations.telegram_bot import send_approval
        fire(send_approval(ctx.user_id, payload))
        await hub.avatar(ctx.user_id, "warning", "Tasdiqingizni kutyapman")
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            await self._set(ap.id, "expired")
            return False
        finally:
            self.waiters.pop(ap.id, None)

    async def decide(self, user_id: str, approval_id: str, approved: bool) -> bool:
        async with SessionLocal() as db:
            ap = await db.get(Approval, approval_id)
            if not ap or ap.user_id != user_id or ap.status != "pending":
                return False
        await self._set(approval_id, "approved" if approved else "rejected")
        fut = self.waiters.get(approval_id)
        if fut and not fut.done():
            fut.set_result(approved)
        await audit(user_id, "approval_decision", {"id": approval_id, "approved": approved}, actor="owner")
        await hub.emit(user_id, "approval_decided", {"id": approval_id, "approved": approved})
        return True

    async def _set(self, approval_id: str, status: str) -> None:
        async with SessionLocal() as db:
            ap = await db.get(Approval, approval_id)
            if ap:
                ap.status, ap.decided_at = status, now()
                await db.commit()


approvals = ApprovalCenter()


def _text_only(messages: list) -> list:
    """Flatten tool_use/tool_result blocks into plain text (for calls made without tools, e.g. ensemble)."""
    out: list[dict] = []
    for m in messages:
        content = m["content"]
        if isinstance(content, str):
            text = content
        else:
            parts = []
            for b in content:
                if b["type"] == "text":
                    parts.append(b["text"])
                elif b["type"] == "tool_use":
                    parts.append(f"[asbob chaqirildi: {b['name']} {json.dumps(b['input'], ensure_ascii=False)[:500]}]")
                elif b["type"] == "tool_result":
                    parts.append(f"[asbob natijasi]\n{str(b['content'])[:4000]}")
            text = "\n".join(parts) or "…"
        if out and out[-1]["role"] == m["role"]:
            out[-1]["content"] += "\n" + text
        else:
            out.append({"role": m["role"], "content": text})
    return out


def _safe_args(args: dict) -> dict:
    out = {}
    for k, v in args.items():
        s = v if isinstance(v, (int, float, bool)) or v is None else str(v)
        out[k] = s[:3000] if isinstance(s, str) else s
    return out


# =================================================================== TOOL EXECUTION
def coerce_args(schema: dict, args: dict) -> dict:
    """Models sometimes send JSON objects as strings (Gemini always does for free-form objects) or numbers as
    strings. Convert them to the types declared in the tool schema; drop arguments the tool doesn't accept."""
    props = (schema or {}).get("properties", {})
    out = {}
    for k, v in (args or {}).items():
        if k not in props:
            continue
        typ = props[k].get("type")
        try:
            if typ == "object" and isinstance(v, str):
                v = json.loads(v) if v.strip() else {}
            elif typ == "number" and isinstance(v, str) and v.strip():
                v = float(v)
            elif typ == "integer" and isinstance(v, (str, float)) and str(v).strip():
                v = int(float(v))
            elif typ == "boolean" and isinstance(v, str):
                v = v.strip().lower() in ("true", "1", "ha", "yes", "да")
            elif typ == "string" and not isinstance(v, str) and v is not None:
                v = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)
        except (ValueError, json.JSONDecodeError):
            pass
        out[k] = v
    return out


async def execute_tool(ctx: ToolContext, name: str, args: dict) -> tuple[str, list]:
    """Returns (text_result, extra_blocks[images])."""
    if emergency.active(ctx.user_id):
        raise StopRequested()
    t = TOOLS.get(name)
    if not t:
        return f"XATO: '{name}' degan asbob yo'q. Mavjud: {', '.join(sorted(TOOLS))}", []
    args = coerce_args(t.parameters, args)
    perms = await get_setting(ctx.user_id, "permissions")
    verdict = validate(name, t.risk, t.module, args, perms)
    if not verdict.allowed:
        await audit(ctx.user_id, f"blocked:{name}", {"args": args, "reason": verdict.reason}, ok=False)
        return f"BLOKLANDI (xavfsizlik): {verdict.reason}", []
    if verdict.needs_approval or t.risk == "critical":
        await hub.emit(ctx.user_id, "agent_step", {"task_id": ctx.task_id, "tool": name, "status": "waiting_approval"})
        ok = await approvals.request(ctx, name, args, verdict.risk, f"ROBIN '{name}' amalini bajarmoqchi")
        if not ok:
            await audit(ctx.user_id, f"rejected:{name}", {"args": args}, ok=False)
            return "Egasi bu amalni RAD ETDI yoki tasdiq muddati tugadi. Boshqa yo'l taklif qil yoki to'xta.", []
    await hub.emit(ctx.user_id, "agent_step", {"task_id": ctx.task_id, "tool": name, "args": _safe_args(args),
                                               "status": "running"})
    try:
        result = await t.func(ctx, **args)
        await audit(ctx.user_id, f"tool:{name}", {"args": args})
    except StopRequested:
        raise
    except TypeError as e:
        await audit(ctx.user_id, f"tool:{name}", {"args": args, "error": str(e)}, ok=False)
        return f"XATO (noto'g'ri argumentlar): {e}. Sxema: {json.dumps(t.parameters, ensure_ascii=False)}", []
    except Exception as e:
        tb = traceback.format_exc()
        await log_error(ctx.user_id, f"tool:{name}", e, tb)
        await audit(ctx.user_id, f"tool:{name}", {"args": args, "error": str(e)}, ok=False)
        return (f"XATO: {type(e).__name__}: {str(e)[:800]}\nSababini tahlil qil va boshqa usul bilan urinib ko'r "
                f"(maks. 3 marta).", [])
    extra = []
    if isinstance(result, dict) and result.get("image_b64"):
        extra.append({"type": "image", "media_type": result.get("media_type", "image/png"), "data": result["image_b64"]})
        result = {k: v for k, v in result.items() if k != "image_b64"}
        result["image"] = "ilova qilindi (pastda)"
    text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
    if len(text) > 24000:
        text = text[:24000] + "\n…(qisqartirildi)"
    await hub.emit(ctx.user_id, "agent_step", {"task_id": ctx.task_id, "tool": name, "status": "done",
                                               "preview": text[:300]})
    return text, extra


async def log_error(user_id: str, where: str, err: Exception, tb: str = "") -> None:
    async with SessionLocal() as db:
        db.add(ErrorLog(user_id=user_id, where=where, error=f"{type(err).__name__}: {err}"[:4000], trace=tb[-8000:]))
        await db.commit()


# =================================================================== AGENT LOOP
async def build_context(ctx: ToolContext, agent: str, query: str, voice_mode: bool = False, extra: str = "") -> tuple[str, list]:
    async with SessionLocal() as db:
        user = await db.get(User, ctx.user_id)
    personality = await get_setting(ctx.user_id, "personality")
    perms = await get_setting(ctx.user_id, "permissions")
    lessons = await ctx.memory.lessons()
    mem = await ctx.memory.context_block(query)
    from backend.agents.devices import bridge
    devs = bridge.online(ctx.user_id)
    if devs:
        dev_txt = f"\nUlangan qurilmalar: {', '.join(d.get('name', d['id']) for d in devs)}"
    elif settings.LOCAL_EXECUTION:
        from backend.agents.computer import _known_folder
        from pathlib import Path
        dev_txt = (f"\nKompyuter: shu server kompyuteri (lokal, {__import__('platform').system()}). "
                   f"Uy papkasi: {Path.home()}; Desktop: {_known_folder('desktop')}; "
                   f"Documents: {_known_folder('documents')}; Downloads: {_known_folder('downloads')}")
    else:
        dev_txt = "\nDIQQAT: hech qanday kompyuter ulanmagan — kompyuter asboblari ishlamaydi."
    system = prompts.system_prompt(personality, agent, (user.full_name or user.username) if user else "do'st", lessons,
                                   mem, extra + dev_txt, voice_mode)
    return system, tools_for(agent, perms)


# Loop guard: models sometimes repeat the same tool endlessly (e.g. web_search 15×).
TOOL_LIMITS = {"web_search": 4, "web_fetch": 5, "screenshot": 15, "screen_read": 10, "search_files": 5}
REPEATABLE = {"screenshot", "screen_read", "wait", "press_key", "scroll", "mouse_click", "click_text", "hotkey",
              "system_resources", "type_text", "list_windows"}  # UI state changes between identical calls


async def run_agent(ctx: ToolContext, text: str, agent: str = "assistant", history: list | None = None,
                    depth: int = 0, voice_mode: bool = False, images: list | None = None,
                    extra: str = "") -> dict:
    brain: Brain = ctx.brain
    system, tool_defs = await build_context(ctx, agent, text, voice_mode, extra)
    if depth >= 1:
        tool_defs = [t for t in tool_defs if t["name"] not in ("delegate", "create_background_task")]
    content: list = [{"type": "text", "text": text}]
    for img in images or []:
        content.insert(0, img)
    messages = list(history or []) + [{"role": "user", "content": content}]
    steps_log = []
    used: dict[str, int] = {}      # loop guard: calls per tool in this run
    seen: dict[tuple, str] = {}    # identical call → cached result
    cfg = await get_setting(ctx.user_id, "brain")
    for step in range(settings.MAX_AGENT_STEPS):
        if emergency.active(ctx.user_id):
            raise StopRequested()
        resp = await brain.complete(system, messages, tools=tool_defs or None)
        if not resp.tool_calls:
            if cfg.get("ensemble") and depth == 0 and len(getattr(brain, "providers", {})) > 1:
                # Ensemble: final answer is drafted by every connected AI and merged by the primary one.
                if steps_log:
                    messages = messages + [{"role": "assistant", "content": resp.text or "…"},
                                           {"role": "user", "content": "Yuqoridagi natijalar asosida yakuniy javobni ber."}]
                try:
                    resp = await brain.ensemble(system, _text_only(messages))
                except Exception as e:
                    log.warning("ensemble failed: %s", e)
            return {"text": resp.text.strip(), "steps": steps_log, "agent": agent, "provider": resp.provider}
        assistant_blocks = ([{"type": "text", "text": resp.text}] if resp.text else []) + \
                           [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.input, "signature": c.signature}
                            for c in resp.tool_calls]
        messages.append({"role": "assistant", "content": assistant_blocks})
        results, extras = [], []
        for call in resp.tool_calls:
            await hub.avatar(ctx.user_id, "working", call.name)
            key = (call.name, json.dumps(call.input or {}, sort_keys=True, ensure_ascii=False))
            used[call.name] = used.get(call.name, 0) + 1
            if key in seen and call.name not in REPEATABLE:
                out, extra_blocks = ("TAKROR: aynan shu chaqiruv allaqachon bajarilgan. Natija:\n" + seen[key][:3000] +
                                     "\nYangi narsa qil yoki shu natija asosida javob ber.", [])
            elif used[call.name] > TOOL_LIMITS.get(call.name, 12):
                out, extra_blocks = (f"LIMIT: '{call.name}' bu vazifada {TOOL_LIMITS.get(call.name, 12)} martadan ko'p "
                                     "chaqirildi. Endi mavjud natijalar asosida yakuniy javob ber.", [])
            else:
                out, extra_blocks = await execute_tool(ctx, call.name, call.input or {})
                seen[key] = out
            steps_log.append({"tool": call.name, "args": _safe_args(call.input or {}), "result": out[:500],
                              "at": datetime.now(timezone.utc).isoformat()})
            results.append({"type": "tool_result", "tool_use_id": call.id, "content": out,
                            "is_error": out.startswith(("XATO", "BLOKLANDI"))})
            extras += extra_blocks
        messages.append({"role": "user", "content": results + extras})
    # step budget exhausted → ask for a final summary without tools
    resp = await brain.complete(system, _text_only(messages + [
        {"role": "assistant", "content": "Qadamlar limiti tugadi."},
        {"role": "user", "content": "Hozirgacha qilinganlarni va qolgan ishlarni qisqa hisobot qilib ber."}]))
    return {"text": resp.text.strip(), "steps": steps_log, "agent": agent, "provider": resp.provider}


# =================================================================== AUTOPILOT
class Autopilot:
    def __init__(self) -> None:
        self.queue: asyncio.PriorityQueue | None = None
        self.running: dict[str, asyncio.Task] = {}
        self.workers: list[asyncio.Task] = []
        self._seq = 0

    def start(self) -> None:
        self.queue = asyncio.PriorityQueue()
        self.workers = [asyncio.create_task(self._worker(i)) for i in range(settings.MAX_PARALLEL_TASKS)]

    async def restore(self) -> None:
        """Re-queue tasks that were queued/running when the server stopped (Backup & Recovery)."""
        async with SessionLocal() as db:
            rows = (await db.scalars(select(Task).where(Task.status.in_(["queued", "running"])))).all()
            for t in rows:
                t.status = "queued"
            await db.commit()
        for t in rows:
            await self._enqueue(t)

    async def stop(self) -> None:
        for w in self.workers:
            w.cancel()
        for t in self.running.values():
            t.cancel()

    async def _enqueue(self, task: Task) -> None:
        self._seq += 1
        await self.queue.put((task.priority, self._seq, task.id))

    async def submit(self, user_id: str, title: str, goal: str, agent: str = "assistant", priority: int = 5,
                     background: bool = False, conversation_id: str = "") -> Task:
        async with SessionLocal() as db:
            t = Task(user_id=user_id, title=title[:300], goal=goal, agent=agent, priority=priority,
                     background=background, conversation_id=conversation_id)
            db.add(t)
            await db.commit()
            await db.refresh(t)
        await self._enqueue(t)
        await hub.emit(user_id, "task_update", {"id": t.id, "status": "queued", "title": t.title})
        return t

    async def cancel(self, user_id: str, task_id: str) -> bool:
        async with SessionLocal() as db:
            t = await db.get(Task, task_id)
            if not t or t.user_id != user_id:
                return False
            if t.status in ("queued", "running", "waiting"):
                t.status, t.finished_at = "cancelled", now()
                await db.commit()
        at = self.running.get(task_id)
        if at:
            at.cancel()
        await hub.emit(user_id, "task_update", {"id": task_id, "status": "cancelled"})
        return True

    async def cancel_all(self, user_id: str | None = None) -> int:
        n = 0
        async with SessionLocal() as db:
            stmt = select(Task).where(Task.status.in_(["queued", "running", "waiting"]))
            if user_id:
                stmt = stmt.where(Task.user_id == user_id)
            for t in (await db.scalars(stmt)).all():
                t.status, t.finished_at = "cancelled", now()
                at = self.running.get(t.id)
                if at:
                    at.cancel()
                n += 1
            await db.commit()
        return n

    async def _worker(self, idx: int) -> None:
        while True:
            _prio, _seq, task_id = await self.queue.get()
            try:
                async with SessionLocal() as db:
                    t = await db.get(Task, task_id)
                if not t or t.status != "queued":
                    continue
                if emergency.active(t.user_id):
                    await self._finish(task_id, "cancelled", error="Favqulodda STOP")
                    continue
                job = asyncio.create_task(self._run(t))
                self.running[task_id] = job
                try:
                    await job
                except asyncio.CancelledError:
                    await self._finish(task_id, "cancelled", error="Bekor qilindi")
                finally:
                    self.running.pop(task_id, None)
            except Exception as e:  # worker must survive
                log.exception("worker %s: %s", idx, e)
            finally:
                self.queue.task_done()

    async def _update(self, task_id: str, **fields) -> None:
        async with SessionLocal() as db:
            t = await db.get(Task, task_id)
            if t:
                for k, v in fields.items():
                    setattr(t, k, v)
                await db.commit()
                await hub.emit(t.user_id, "task_update", {"id": t.id, "status": t.status, "title": t.title,
                                                          "plan": t.plan})

    async def _finish(self, task_id: str, status: str, result: str = "", error: str = "", review: str = "") -> None:
        await self._update(task_id, status=status, result=result, error=error, review=review, finished_at=now())

    async def _run(self, t: Task) -> None:
        await self._update(t.id, status="running", started_at=now())
        brain = await get_brain(t.user_id)
        ctx = ToolContext(user_id=t.user_id, task_id=t.id, brain=brain, memory=Memory(t.user_id, brain.keys))
        try:
            mem_ctx = await ctx.memory.context_block(t.goal)
            plan = await make_plan(brain, t.goal, mem_ctx)
            steps = plan["steps"]
            await self._update(t.id, plan=steps, title=plan["title"][:300] if t.title == t.goal[:300] else t.title)
            results: dict[int, str] = {}
            log_all = []
            while True:
                batch = ready_steps(steps)
                if not batch:
                    break
                for s in batch:
                    s["status"] = "running"
                await self._update(t.id, plan=steps)

                async def run_step(s):
                    deps = "\n\n".join(f"[{d}-bosqich natijasi]\n{results.get(d, '')[:4000]}" for d in s["depends_on"])
                    prompt = (f"UMUMIY MAQSAD: {t.goal}\n\nSENING BOSQICHING ({s['id']}): {s['action']}\n"
                              f"Kutilgan natija: {s['expected']}\n\n{deps}\nBosqichni bajar va natijani aniq yoz.")
                    return s, await run_agent(ctx, prompt, agent=s["agent"], depth=1)

                outs = await asyncio.gather(*[run_step(s) for s in batch], return_exceptions=True)
                for o in outs:
                    if isinstance(o, StopRequested):
                        raise o
                    if isinstance(o, Exception):
                        for s in batch:
                            if s["status"] == "running":
                                s["status"] = "failed"
                                results[s["id"]] = f"XATO: {o}"
                        continue
                    s, res = o
                    s["status"] = "done"
                    results[s["id"]] = res["text"]
                    log_all += [{"step": s["id"], **x} for x in res["steps"]]
                await self._update(t.id, plan=steps, steps_log=log_all[-300:])
                if any(s["status"] == "failed" for s in steps):
                    # dependants of failed steps cannot run
                    failed = {s["id"] for s in steps if s["status"] == "failed"}
                    for s in steps:
                        if s["status"] == "pending" and set(s["depends_on"]) & failed:
                            s["status"] = "skipped"
            summary_in = "\n\n".join(f"[{s['id']}. {s['action']}] ({s['status']})\n{results.get(s['id'], '')[:5000]}"
                                     for s in steps)
            final = await run_agent(ctx, f"MAQSAD: {t.goal}\n\nBOSQICHLAR NATIJALARI:\n{summary_in}\n\n"
                                         f"Topshiriladigan natija: {plan['deliverable']}.\nYakuniy natijani foydalanuvchiga "
                                         f"topshir: nima qilindi, natija (fayl yo'llari bilan), topilgan muammolar.",
                                    agent=t.agent, depth=1)
            result = final["text"]
            review = {}
            cfg = await get_setting(t.user_id, "brain")
            if cfg.get("self_review", True):
                review = await brain.review(t.goal, result + "\n\n" + summary_in[:6000])
                if review.get("ok") is False and review.get("fix"):
                    fix = await run_agent(ctx, f"MAQSAD: {t.goal}\n\nOLDINGI NATIJA:\n{result}\n\nTEKSHIRUVCHI "
                                               f"TOPGAN MUAMMOLAR: {review.get('issues')}\nTUZATISH: {review['fix']}\n"
                                               "Muammolarni tuzat va yakuniy natijani qayta topshir.", agent=t.agent, depth=1)
                    result = fix["text"]
            status = "failed" if all(s["status"] != "done" for s in steps) else "done"
            await self._finish(t.id, status, result=result, review=json.dumps(review, ensure_ascii=False))
            await ctx.memory.remember(f"Vazifa '{plan['title']}' bajarildi. Natija: {result[:600]}", "workflow",
                                      plan["title"][:120], 0.5)
            if t.conversation_id:
                await ctx.memory.add_message(t.conversation_id, "assistant", f"✅ **{plan['title']}**\n\n{result}",
                                             {"task_id": t.id})
            from backend.memory.notes import add_note
            steps_md = "\n".join(f"{s['id']}. [{s['status']}] ({s['agent']}) {s['action']}" for s in steps)
            note_body = (f"# {plan['title']}\n\n**Maqsad:** {t.goal}\n\n## Natija\n{result}\n\n## Reja\n{steps_md}"
                         + (f"\n\n## Self-Review\n{json.dumps(review, ensure_ascii=False)}" if review else ""))
            await add_note(t.user_id, f"{'✅' if status == 'done' else '❌'} Vazifa: {plan['title']}", note_body, "task")
            await hub.notify(t.user_id, f"Vazifa {'bajarildi' if status == 'done' else 'muvaffaqiyatsiz'}: {plan['title']}",
                             result[:1500], "success" if status == "done" else "error")
            await hub.avatar(t.user_id, "happy" if status == "done" else "warning")
        except StopRequested:
            await self._finish(t.id, "cancelled", error="Favqulodda STOP")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            tb = traceback.format_exc()
            await log_error(t.user_id, f"task:{t.id}", e, tb)
            await self._finish(t.id, "failed", error=f"{type(e).__name__}: {e}")
            await hub.notify(t.user_id, f"Vazifa xato bilan tugadi: {t.title}", str(e)[:800], "error")


autopilot = Autopilot()


# =================================================================== SAVED COMMANDS
def match_command(text: str, commands: list[Command]) -> Command | None:
    t = text.lower().strip(" .!?")
    for prefix in ("robin,", "robin", "робин,", "робин"):
        if t.startswith(prefix):
            t = t[len(prefix):].strip(" ,")
    for c in commands:
        if not c.enabled:
            continue
        phrases = [c.name.lower()] + [x.lower() for x in (c.triggers or [])]
        if any(t == p or (len(p) > 5 and p in t) for p in phrases if p):
            return c
    return None


async def run_command(ctx: ToolContext, cmd: Command) -> dict:
    out = []
    await hub.avatar(ctx.user_id, "working", cmd.name)
    for i, step in enumerate(cmd.steps or []):
        tool_name = step.get("tool", "")
        args = step.get("args") or {}
        if tool_name in ("ai", "ask_robin"):
            res = await run_agent(ctx, args.get("prompt", step.get("note", "")), agent=args.get("agent", "assistant"),
                                  depth=1)
            out.append({"step": i + 1, "tool": "ai", "result": res["text"][:1500]})
            continue
        text, _ = await execute_tool(ctx, tool_name, args)
        out.append({"step": i + 1, "tool": tool_name, "result": text[:600]})
        if text.startswith(("XATO", "BLOKLANDI")) and not step.get("continue_on_error"):
            break
    async with SessionLocal() as db:
        c = await db.get(Command, cmd.id)
        if c:
            c.run_count += 1
            c.last_run = now()
            await db.commit()
    ok = all(not o["result"].startswith(("XATO", "BLOKLANDI")) for o in out)
    return {"command": cmd.name, "ok": ok, "steps": out}


async def run_command_by_name(ctx: ToolContext, name: str) -> dict:
    async with SessionLocal() as db:
        rows = (await db.scalars(select(Command).where(Command.user_id == ctx.user_id))).all()
    cmd = next((c for c in rows if c.name.lower() == name.lower()), None) or match_command(name, rows)
    if not cmd:
        return {"ok": False, "error": f"'{name}' nomli buyruq topilmadi"}
    return await run_command(ctx, cmd)


# =================================================================== CHAT ENTRY POINT
async def access_block(user_id: str, channel: str, voice_mode: bool = False) -> str | None:
    """Admin policy gate for every channel (web, ws, voice, telegram, desktop). None = allowed."""
    from backend.security.services import allowed, check_limit, denied_text
    async with SessionLocal() as db:
        u = await db.get(User, user_id)
    if not u or not u.is_active:
        return "🔒 Hisobingiz administrator tomonidan bloklangan."
    if channel == "task":
        return None
    if not await allowed(user_id, "chat"):
        return denied_text("chat")
    if channel == "telegram" and not await allowed(user_id, "telegram"):
        return denied_text("telegram")
    if channel == "desktop" and not await allowed(user_id, "devices"):
        return denied_text("devices")
    return await check_limit(user_id, voice_mode)


async def claude_command(user_id: str, task: str) -> str:
    """`/claude <vazifa>` — admin only; works only while the 🤖 Claude icon in the Admin panel is lit."""
    from backend.integrations.claude_code import bridge
    async with SessionLocal() as db:
        u = await db.get(User, user_id)
    if not u or not u.is_admin:
        return "🔒 /claude buyrug'i faqat administrator uchun."
    st = bridge.status()
    if not task:
        return (f"🤖 Claude: {'🟢 yoqilgan' if st['enabled'] else '⚫ o‘chiq'}"
                f"{' · ishlayapti' if st['running'] else ''}\nCLI: {st['version'] or 'topilmadi'}\n"
                "Foydalanish: /claude <vazifa>  (masalan: /claude mijoz paneliga yangi tugma qo'sh)")
    if not st["enabled"]:
        return "⚫ Claude o'chiq. Admin panel → 🤖 Claude ikonkasini yoqing, keyin qayta yuboring."
    await audit(user_id, "admin:claude_task", {"text": task[:300], "via": "chat"}, actor="admin")
    return "🤖 Claude:\n" + await bridge.ask(task, u.username)


async def chat(user_id: str, text: str, conversation_id: str | None = None, voice_mode: bool = False,
               images: list | None = None, channel: str = "web", device_id: str = "") -> dict:
    blocked = await access_block(user_id, channel, voice_mode)
    if blocked:
        return {"conversation_id": conversation_id, "message_id": None, "reply": blocked, "meta": {"blocked": True}}
    from backend.security.services import allowed
    if voice_mode and not await allowed(user_id, "voice"):
        voice_mode = False
    brain = await get_brain(user_id)
    memory = Memory(user_id, brain.keys)
    conv = await memory.get_or_create_conversation(conversation_id, text[:60])
    history = await memory.recent_messages(conv.id)
    await memory.add_message(conv.id, "user", text, {"channel": channel, "voice": voice_mode})
    ctx = ToolContext(user_id=user_id, conversation_id=conv.id, brain=brain, memory=memory, device_id=device_id)
    await hub.avatar(user_id, "thinking")
    meta: dict = {"channel": channel}
    try:
        if emergency.active(user_id):
            reply = "⛔ Favqulodda STOP faol. Davom etish uchun Dashboard'da STOP'ni o'chiring."
        else:
            async with SessionLocal() as db:
                cmds = (await db.scalars(select(Command).where(Command.user_id == user_id))).all()
            cmd = match_command(text, cmds)
            if text.strip().lower().startswith("/claude"):
                reply = await claude_command(user_id, text.strip()[7:].strip())
                meta.update({"claude": True})
            elif cmd:
                res = await run_command(ctx, cmd)
                meta.update({"command": cmd.name, "steps": res["steps"]})
                reply = (f"'{cmd.name}' buyrug'i bajarildi ✅" if res["ok"] else
                         f"'{cmd.name}' buyrug'ida muammo: {res['steps'][-1]['result'][:300] if res['steps'] else ''}")
            elif not brain.available:
                raise NoProviderError("AI kaliti sozlanmagan")
            else:
                cfg = await get_setting(user_id, "brain")
                route = await brain.route(text) if cfg.get("multi_brain", True) else {"agent": "assistant"}
                agent = route.get("agent", "assistant")
                meta.update({"agent": agent, "emotion": route.get("emotion"), "language": route.get("language")})
                emo = route.get("emotion")
                extra = f"\nFoydalanuvchi kayfiyati (taxmin): {emo}." if emo and emo != "neutral" else ""
                if route.get("complex") and not voice_mode and len(text) > 40 and channel != "task" and                         await allowed(user_id, "autopilot"):
                    task = await autopilot.submit(user_id, route.get("title") or text[:80], text, agent=agent,
                                                  conversation_id=conv.id)
                    meta["task_id"] = task.id
                    lang = route.get("language", "uz")
                    reply = {"ru": f"Понял. Составил задачу «{task.title}» — выполняю на Autopilot, результат пришлю сюда.",
                             "en": f"Got it. I created the task “{task.title}” and I'm running it on Autopilot — "
                                   f"I'll post the result here."}.get(lang, f"Tushundim. «{task.title}» vazifasini "
                                   "Autopilot'ga qo'ydim — reja tuzib bosqichma-bosqich bajaraman va natijani shu "
                                   "yerga yozaman.")
                else:
                    res = await run_agent(ctx, text, agent=agent, history=history, voice_mode=voice_mode,
                                          images=images, extra=extra)
                    reply = res["text"] or "Bajarildi."
                    meta.update({"steps": res["steps"], "provider": res.get("provider")})
    except NoProviderError:
        reply = ("Men hali AI miyaga ulanmaganman 🙂 Dashboard → Brain bo'limida Claude, ChatGPT yoki Gemini "
                 "API kalitini kiriting. Saqlangan buyruqlar (Commands) esa hozir ham ishlaydi.")
    except StopRequested:
        reply = "⛔ To'xtatildi (favqulodda STOP)."
    except ProviderError as e:
        await log_error(user_id, "chat:provider", e)
        reply = provider_error_message(str(e), meta.get("language") or "uz")
        meta["error"] = str(e)[:500]
    except Exception as e:
        tb = traceback.format_exc()
        await log_error(user_id, "chat", e, tb)
        reply = await explain_error(brain, e, text)
        meta["error"] = str(e)[:500]
    mid = await memory.add_message(conv.id, "assistant", reply, meta)
    await hub.avatar(user_id, "speaking" if voice_mode else "idle", reply[:200])
    fire(post_turn(user_id, conv.id, brain))
    return {"conversation_id": conv.id, "message_id": mid, "reply": reply, "meta": meta}


def provider_error_message(err: str, lang: str = "uz") -> str:
    """Human explanation of AI-provider failures (no raw JSON for the user)."""
    e = err.lower()
    if "429" in e or "quota" in e or "rate" in e:
        kind = "quota"
    elif any(c in e for c in (" 503", " 500", " 529", "overloaded", "high demand", "timeout")):
        kind = "busy"
    elif any(c in e for c in (" 401", " 403", "api key", "api_key", "permission")):
        kind = "key"
    else:
        kind = "other"
    msgs = {
        "uz": {"quota": "⏳ AI kvotasi vaqtincha tugadi (API kalitingizning daqiqalik yoki kunlik limiti). Bir-ikki "
                        "daqiqadan keyin qayta urinib ko'ring. Doimiy ishlash uchun Google AI Studio'da billing'ni "
                        "yoqing yoki Brain bo'limida ikkinchi AI (Claude/ChatGPT) kalitini qo'shing.",
               "busy": "⏳ AI serverlari hozir juda band. Bir necha soniyadan keyin qayta yozing — men boshqa "
                       "modellarni ham sinab ko'rdim.",
               "key": "🔑 API kalit noto'g'ri yoki ruxsati yo'q. Dashboard → Brain bo'limida kalitni tekshiring.",
               "other": "⚠️ AI xizmatidan javob olib bo'lmadi. Xato jurnalga yozildi (Settings → Admin)."},
        "ru": {"quota": "⏳ Квота AI временно исчерпана. Попробуйте через минуту или подключите второй AI в Brain.",
               "busy": "⏳ Серверы AI сейчас перегружены. Повторите через несколько секунд.",
               "key": "🔑 API-ключ неверный или без доступа. Проверьте его в разделе Brain.",
               "other": "⚠️ Не удалось получить ответ от AI. Ошибка записана в журнал."},
        "en": {"quota": "⏳ The AI quota is temporarily used up. Try again in a minute or add a second AI key in Brain.",
               "busy": "⏳ The AI servers are overloaded right now. Please retry in a few seconds.",
               "key": "🔑 The API key is invalid or lacks access. Check it in Brain.",
               "other": "⚠️ Couldn't get a reply from the AI service. The error was logged."},
    }
    return msgs.get(lang, msgs["uz"])[kind]


async def explain_error(brain: Brain, err: Exception, text: str) -> str:
    """Error-handling intelligence: understandable explanation instead of a raw stack trace."""
    try:
        data = await brain.ask_json(prompts.ERROR_DIAGNOSE_PROMPT, f"So'rov: {text[:1000]}\nXato: {type(err).__name__}: "
                                                                   f"{str(err)[:1500]}", max_tokens=600)
        if data.get("user_message"):
            return "⚠️ " + data["user_message"]
    except Exception:
        pass
    return f"⚠️ Kechirasiz, xatolik yuz berdi: {str(err)[:300]}. Xato jurnalga yozildi, admin ko'rib chiqadi."


async def post_turn(user_id: str, conversation_id: str, brain: Brain) -> None:
    """After an exchange: extract long-term memories and refresh title/summary.
    Quota-friendly: memory extraction runs when the user shares something personal or every 3rd turn;
    title + summary + project come from ONE call on the 1st turn and every 6th turn."""
    if not brain.available:
        return
    try:
        memory = Memory(user_id, brain.keys)
        msgs = await memory.recent_messages(conversation_id, limit=12)
        user_msgs = [m["content"] for m in msgs if m["role"] == "user"]
        if not user_msgs:
            return
        async with SessionLocal() as db:
            from sqlalchemy import func as _f
            from backend.memory.database import Message
            turns = await db.scalar(select(_f.count()).select_from(Message).where(
                Message.conversation_id == conversation_id, Message.role == "user")) or 0
        transcript = "\n".join(f"{m['role']}: {m['content'][:1500]}" for m in msgs[-6:])
        last = user_msgs[-1].lower()
        personal = MEMORY_CUES.search(last) is not None
        if personal or turns % 3 == 0:
            data = await brain.ask_json(prompts.MEMORY_EXTRACT_PROMPT, transcript, max_tokens=800)
            for m in (data.get("memories") or [])[:5]:
                if m.get("content") and float(m.get("importance", 0.5)) >= 0.4:
                    await memory.remember(m["content"], m.get("kind", "fact"), m.get("subject", ""),
                                          float(m.get("importance", 0.5)))
        if turns == 1 or turns % 6 == 0:
            data = await brain.ask_json(
                'Suhbatni tahlil qil. Faqat JSON: {"title": "3-6 so\'zli sarlavha", "project": "loyiha nomi yoki \'\'", '
                '"summary": "3-5 jumla: mavzu, qarorlar, qolgan ishlar"}', transcript, max_tokens=500)
            async with SessionLocal() as db:
                conv = await db.get(Conversation, conversation_id)
                if conv:
                    if data.get("summary"):
                        conv.summary = str(data["summary"])[:4000]
                    if data.get("project"):
                        conv.project = str(data["project"])[:120]
                    if data.get("title"):
                        conv.title = str(data["title"]).strip('" ')[:200]
                    await db.commit()
    except Exception as e:
        log.debug("post_turn failed: %s", e)


MEMORY_CUES = re.compile(r"eslab qol|esla\b|yodda tut|remember|запомни|\bmen\b|\bmening\b|\bmenga\b|loyiha|project|"
                         r"проект|\bя\b|\bмой\b|\bмоя\b|\bmy\b|\bi am\b|\bi'm\b|yoqadi|yoqtiraman|prefer|afzal")


# =================================================================== SELF-LEARNING
async def learn_from_feedback(user_id: str, message_id: int | None, rating: int, text: str,
                              apply_settings: bool = False) -> dict:
    brain = await get_brain(user_id)
    lesson, change = "", None
    if brain.available and (text or rating < 0):
        data = await brain.ask_json(prompts.LESSON_PROMPT, f"Baho: {rating}\nIzoh/tuzatish: {text}", max_tokens=400)
        lesson, change = data.get("lesson", ""), data.get("settings_change")
    elif text:
        lesson = text[:500]
    async with SessionLocal() as db:
        fb = Feedback(user_id=user_id, message_id=message_id, rating=rating, text=text, lesson=lesson)
        db.add(fb)
        await db.commit()
    applied = False
    if apply_settings and isinstance(change, dict) and change.get("key") in ("personality", "brain", "voice", "avatar"):
        await set_setting(user_id, change["key"], change.get("value") or {})
        applied = True
    await audit(user_id, "self_learning", {"lesson": lesson, "settings_change": change, "applied": applied})
    if lesson:
        from backend.memory.notes import add_note
        body = f"**Qoida:** {lesson}\n\n**Sizning izohingiz:** {text or '—'} (baho: {rating})"
        if applied:
            body += "\n\nSozlamalar avtomatik moslashtirildi."
        await add_note(user_id, f"🎓 O'rgangan qoidam: {lesson[:80]}", body, "lesson")
    return {"lesson": lesson, "settings_change": change, "applied": applied}


async def diagnose_errors(user_id: str, limit: int = 10) -> list[dict]:
    """Self-repair: AI diagnoses recent unresolved errors and proposes fixes for the admin."""
    brain = await get_brain(user_id)
    out = []
    async with SessionLocal() as db:
        rows = (await db.scalars(select(ErrorLog).where(ErrorLog.resolved.is_(False), ErrorLog.diagnosis == "")
                                 .order_by(ErrorLog.id.desc()).limit(limit))).all()
        for e in rows:
            if not brain.available:
                break
            try:
                r = await brain.complete(prompts.ERROR_DIAGNOSE_PROMPT,
                                         [{"role": "user", "content": f"Joy: {e.where}\nXato: {e.error}\nTrace:\n{e.trace[-4000:]}"}],
                                         max_tokens=900, temperature=0.1)
                data = parse_json(r.text)
                e.diagnosis = data.get("diagnosis", r.text[:1500])
                e.fix_proposal = data.get("fix_proposal", "")
                out.append({"id": e.id, "where": e.where, "diagnosis": e.diagnosis, "fix": e.fix_proposal,
                            "settings_change": data.get("settings_change")})
            except Exception as ex:
                out.append({"id": e.id, "error": str(ex)})
        await db.commit()
    return out
