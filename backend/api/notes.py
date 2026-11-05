"""Notes API: system guides (read-only, from /notes/*.md) + user notes (auto-written by ROBIN or manual)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.memory.database import Note, User, get_session
from backend.memory.notes import system_notes
from backend.security.auth import current_user
from backend.security.services import require_service

router = APIRouter(prefix="/api/notes", tags=["notes"], dependencies=[Depends(require_service("notes"))])

CATEGORIES = {"guide": "📘 Yo'riqnomalar", "task": "✅ Vazifalar", "command": "⚡ Buyruqlar", "lesson": "🎓 O'rgangan qoidalar",
              "journal": "📓 Kunlik jurnal", "robin": "🤖 ROBIN yozuvlari", "reminder": "⏰ Eslatmalar", "user": "✍️ Mening qaydlarim"}


class NoteIn(BaseModel):
    title: str
    body: str = ""
    category: str = "user"
    pinned: bool = False


def out(n: Note) -> dict:
    return {"id": n.id, "title": n.title, "body": n.body, "category": n.category, "auto": n.auto, "pinned": n.pinned,
            "system": False, "created_at": n.created_at.isoformat(), "updated_at": n.updated_at.isoformat()}


@router.get("")
async def list_notes(q: str = "", category: str = "", user: User = Depends(current_user),
                     db: AsyncSession = Depends(get_session)):
    stmt = select(Note).where(Note.user_id == user.id)
    if category and category != "guide":
        stmt = stmt.where(Note.category == category)
    if q:
        stmt = stmt.where(Note.title.ilike(f"%{q}%") | Note.body.ilike(f"%{q}%"))
    rows = [] if category == "guide" else (await db.scalars(
        stmt.order_by(desc(Note.pinned), desc(Note.created_at)).limit(500))).all()
    sys_notes = [] if category not in ("", "guide") else [
        s for s in system_notes() if not q or q.lower() in (s["title"] + s["body"]).lower()]
    return {"categories": CATEGORIES, "items": sys_notes + [out(n) for n in rows]}


@router.post("")
async def create_note(data: NoteIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_session)):
    if not data.title.strip():
        raise HTTPException(400, "Sarlavha kerak")
    n = Note(user_id=user.id, title=data.title.strip()[:300], body=data.body,
             category=data.category if data.category in CATEGORIES and data.category != "guide" else "user",
             pinned=data.pinned, auto=False)
    db.add(n)
    await db.commit()
    return out(n)


@router.put("/{nid}")
async def update_note(nid: str, data: NoteIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_session)):
    n = await db.get(Note, nid)
    if not n or n.user_id != user.id:
        raise HTTPException(404, "Faqat o'z qaydlaringizni tahrirlash mumkin")
    n.title, n.body, n.pinned = data.title.strip()[:300] or n.title, data.body, data.pinned
    await db.commit()
    return out(n)


@router.delete("/{nid}")
async def delete_note(nid: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_session)):
    await db.execute(delete(Note).where(Note.id == nid, Note.user_id == user.id))
    await db.commit()
    return {"ok": True}


@router.get("/export.md", response_class=PlainTextResponse)
async def export_all(user: User = Depends(current_user), db: AsyncSession = Depends(get_session)):
    rows = (await db.scalars(select(Note).where(Note.user_id == user.id).order_by(Note.created_at))).all()
    parts = [s["body"] for s in system_notes()] + [
        f"# {n.title}\n_{n.created_at:%Y-%m-%d %H:%M} · {CATEGORIES.get(n.category, n.category)}_\n\n{n.body}" for n in rows]
    return PlainTextResponse("\n\n---\n\n".join(parts), headers={
        "Content-Disposition": 'attachment; filename="ROBIN_notes.md"'})
