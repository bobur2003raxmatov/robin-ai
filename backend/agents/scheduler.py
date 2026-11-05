"""Background Agent & Reminder System: runs on the server even when the user is away.

* reminders / meetings → Smart Notifications (dashboard, desktop widget, Telegram)
* scheduled commands: "daily 09:00", "weekdays 18:30", "every 30m", "hourly"
* trading simulator: paper SL/TP checks
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from backend.agents.events import hub
from backend.memory.database import Command, PaperAccount, Reminder, SessionLocal

log = logging.getLogger("robin.scheduler")


def is_due(schedule: str, last_run: datetime | None, now_local: datetime) -> bool:
    s = (schedule or "").strip().lower()
    if not s:
        return False
    last = last_run.astimezone() if last_run else None
    if s.startswith("every "):
        val = s[6:].strip()
        mins = int(val[:-1]) * (60 if val.endswith("h") else 1) if val[:-1].isdigit() else 60
        return last is None or now_local - last >= timedelta(minutes=mins)
    if s == "hourly":
        return last is None or now_local - last >= timedelta(hours=1)
    parts = s.split()
    if len(parts) == 2 and ":" in parts[1]:
        kind, hm = parts
        h, m = map(int, hm.split(":"))
        if kind == "weekdays" and now_local.weekday() >= 5:
            return False
        if kind == "weekly" and last and now_local - last < timedelta(days=6, hours=23):
            return False
        target = now_local.replace(hour=h, minute=m, second=0, microsecond=0)
        return now_local >= target and (last is None or last < target) and now_local - target < timedelta(minutes=30)
    return False


async def tick_reminders() -> None:
    now = datetime.now(timezone.utc)
    async with SessionLocal() as db:
        rows = (await db.scalars(select(Reminder).where(Reminder.done.is_(False), Reminder.notified.is_(False),
                                                        Reminder.due_at <= now + timedelta(minutes=1)))).all()
        upcoming = (await db.scalars(select(Reminder).where(
            Reminder.done.is_(False), Reminder.kind == "meeting", Reminder.notified.is_(False),
            Reminder.due_at > now, Reminder.due_at <= now + timedelta(minutes=15)))).all()
        for r in rows:
            icon = "📅" if r.kind == "meeting" else "⏰"
            await hub.notify(r.user_id, f"{icon} {r.title}", r.note or r.due_at.astimezone().strftime("%H:%M"), "warning")
            await hub.avatar(r.user_id, "warning", r.title)
            if r.repeat in ("daily", "weekly"):
                r.due_at = r.due_at + timedelta(days=1 if r.repeat == "daily" else 7)
            else:
                r.notified = True
        for r in upcoming:
            key = f"pre_{r.id}"
            if key not in _pre_notified:
                _pre_notified.add(key)
                mins = int((r.due_at - now).total_seconds() // 60)
                await hub.notify(r.user_id, f"📅 {mins} daqiqadan keyin: {r.title}", r.note, "info")
        await db.commit()


_pre_notified: set[str] = set()


async def tick_commands() -> None:
    from backend.agents.executor import ToolContext, run_command
    from backend.ai.brain import get_brain
    from backend.memory.memory import Memory
    now_local = datetime.now().astimezone()
    async with SessionLocal() as db:
        rows = (await db.scalars(select(Command).where(Command.enabled.is_(True), Command.schedule != ""))).all()
    for c in rows:
        if is_due(c.schedule, c.last_run, now_local):
            brain = await get_brain(c.user_id)
            ctx = ToolContext(user_id=c.user_id, brain=brain, memory=Memory(c.user_id, brain.keys))
            try:
                res = await run_command(ctx, c)
                await hub.notify(c.user_id, f"Avtomatik buyruq: {c.name} {'✅' if res['ok'] else '⚠️'}",
                                 "\n".join(f"{s['step']}. {s['tool']}: {s['result'][:150]}" for s in res["steps"]),
                                 "success" if res["ok"] else "warning")
            except Exception as e:
                await hub.notify(c.user_id, f"Avtomatik buyruq xatosi: {c.name}", str(e)[:500], "error")


async def tick_trading() -> None:
    from backend.trading.broker import check_stops
    async with SessionLocal() as db:
        users = (await db.scalars(select(PaperAccount.user_id))).all()
    for uid in users:
        try:
            for c in await check_stops(uid):
                if c.get("ok"):
                    await hub.notify(uid, f"Demo savdo yopildi: {c['symbol']}", f"PnL: {c['pnl']}",
                                     "success" if c["pnl"] > 0 else "warning")
        except Exception as e:
            log.debug("trading tick: %s", e)


STATE = {"last_tick": 0.0, "started": time.time(), "journal_day": datetime.now().date()}


async def tick_journal() -> None:
    """At day rollover ROBIN writes yesterday's journal note for every user that had activity."""
    today = datetime.now().date()
    if today == STATE["journal_day"]:
        return
    yesterday = STATE["journal_day"]
    STATE["journal_day"] = today
    from backend.memory.database import User
    from backend.memory.notes import daily_journal
    async with SessionLocal() as db:
        users = (await db.scalars(select(User.id))).all()
    day = datetime.combine(yesterday, datetime.min.time()).astimezone()
    for uid in users:
        try:
            await daily_journal(uid, day)
        except Exception as e:
            log.debug("journal: %s", e)


async def loop() -> None:
    n = 0
    while True:
        try:
            STATE["last_tick"] = time.time()
            await tick_reminders()
            await tick_commands()
            await tick_journal()
            if n % 2 == 0:
                await tick_trading()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.exception("scheduler: %s", e)
        n += 1
        await asyncio.sleep(30)
