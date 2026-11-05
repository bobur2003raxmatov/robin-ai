"""Notes service.

* System notes (read-only guides) live as Markdown files in /notes — the project's documentation: work log,
  user guide, AI provider guide, roadmap reminders. Edit those files and the dashboard shows the new text.
* User notes live in the DB. ROBIN writes many of them automatically (auto=True): finished Autopilot tasks,
  new/learned commands, self-learning lessons, the daily journal, and anything the user asks it to note down.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from backend.config import BASE_DIR
from backend.memory.database import AuditLog, Note, SessionLocal, Task

log = logging.getLogger("robin.notes")
NOTES_DIR = BASE_DIR / "notes"
NOTES_DIR.mkdir(exist_ok=True)


def system_notes() -> list[dict]:
    out = []
    for p in sorted(NOTES_DIR.glob("*.md")):
        text = p.read_text(encoding="utf-8")
        m = re.match(r"#\s+(.+)", text)
        out.append({"id": f"sys:{p.stem}", "title": m.group(1).strip() if m else p.stem, "body": text,
                    "category": "guide", "auto": False, "pinned": True, "system": True,
                    "updated_at": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat()})
    return out


async def add_note(user_id: str, title: str, body: str = "", category: str = "robin", auto: bool = True,
                   pinned: bool = False) -> str:
    """Never raises — a failed note must not break the action that triggered it."""
    try:
        async with SessionLocal() as db:
            n = Note(user_id=user_id, title=title[:300], body=body, category=category, auto=auto, pinned=pinned)
            db.add(n)
            await db.commit()
        try:
            from backend.agents.events import hub
            await hub.emit(user_id, "notes_changed", {"id": n.id, "title": n.title})
        except Exception:
            pass
        return n.id
    except Exception as e:  # pragma: no cover
        log.warning("note failed: %s", e)
        return ""


async def daily_journal(user_id: str, day: datetime) -> str | None:
    """Plain summary of what ROBIN did during `day` (local date). No AI needed."""
    start = day.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    end = start + timedelta(days=1)
    async with SessionLocal() as db:
        rows = (await db.execute(select(AuditLog.action, AuditLog.ok, func.count()).where(
            AuditLog.user_id == user_id, AuditLog.created_at >= start, AuditLog.created_at < end)
            .group_by(AuditLog.action, AuditLog.ok))).all()
        tasks = (await db.scalars(select(Task).where(Task.user_id == user_id, Task.created_at >= start,
                                                     Task.created_at < end))).all()
    if not rows and not tasks:
        return None
    tool_ok = sum(n for a, ok, n in rows if a.startswith("tool:") and ok)
    tool_err = sum(n for a, ok, n in rows if a.startswith("tool:") and not ok)
    top: dict[str, int] = {}
    for a, _ok, n in rows:
        if a.startswith("tool:"):
            top[a[5:]] = top.get(a[5:], 0) + n
    lines = [f"# Kunlik jurnal — {day:%Y-%m-%d}", "",
             f"- Bajarilgan amallar: **{tool_ok}** ta" + (f" (xato bilan: {tool_err})" if tool_err else ""),
             f"- Autopilot vazifalari: **{len(tasks)}** ta "
             f"(bajarildi: {sum(t.status == 'done' for t in tasks)}, muvaffaqiyatsiz: {sum(t.status == 'failed' for t in tasks)})"]
    if top:
        lines += ["", "## Eng ko'p ishlatilgan asboblar"] + \
                 [f"- {k}: {v}" for k, v in sorted(top.items(), key=lambda x: -x[1])[:8]]
    if tasks:
        lines += ["", "## Vazifalar"] + [f"- [{t.status}] {t.title}" for t in tasks[:20]]
    other = [(a, n) for a, ok, n in rows if not a.startswith("tool:")]
    if other:
        lines += ["", "## Boshqa hodisalar"] + [f"- {a}: {n}" for a, n in other[:12]]
    return await add_note(user_id, f"📓 Kunlik jurnal — {day:%d.%m.%Y}", "\n".join(lines), "journal")
