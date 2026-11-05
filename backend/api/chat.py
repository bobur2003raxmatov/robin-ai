from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agents.events import hub
from backend.agents.executor import chat, learn_from_feedback
from backend.memory.database import Conversation, Message, User, get_session
from backend.security.auth import current_user, ws_user
from backend.security.services import require_service

router = APIRouter(prefix="/api/chat", tags=["chat"], dependencies=[Depends(require_service("chat"))])


class ChatIn(BaseModel):
    text: str
    conversation_id: str | None = None
    voice: bool = False
    image_b64: str | None = None       # Live Vision: camera frame / screenshot / chart picture
    image_type: str = "image/png"
    device_id: str = ""


class FeedbackIn(BaseModel):
    message_id: int | None = None
    rating: int = 0
    text: str = ""
    apply_settings: bool = False


@router.post("")
async def send(data: ChatIn, user: User = Depends(current_user)):
    if not data.text.strip() and not data.image_b64:
        raise HTTPException(400, "Bo'sh xabar")
    images = None
    if data.image_b64:
        b64 = data.image_b64.split(",", 1)[-1]
        images = [{"type": "image", "media_type": data.image_type, "data": b64}]
    return await chat(user.id, data.text or "Bu rasmni tahlil qil.", data.conversation_id, data.voice, images,
                      device_id=data.device_id)


@router.get("/conversations")
async def conversations(q: str = "", user: User = Depends(current_user), db: AsyncSession = Depends(get_session)):
    stmt = select(Conversation).where(Conversation.user_id == user.id)
    if q:
        stmt = stmt.where(Conversation.title.ilike(f"%{q}%") | Conversation.summary.ilike(f"%{q}%"))
    rows = (await db.scalars(stmt.order_by(desc(Conversation.updated_at)).limit(200))).all()
    return [{"id": c.id, "title": c.title, "project": c.project, "summary": c.summary,
             "updated_at": c.updated_at.isoformat()} for c in rows]


@router.get("/conversations/{cid}")
async def conversation(cid: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_session)):
    c = await db.get(Conversation, cid)
    if not c or c.user_id != user.id:
        raise HTTPException(404)
    msgs = (await db.scalars(select(Message).where(Message.conversation_id == cid).order_by(Message.id))).all()
    return {"id": c.id, "title": c.title, "summary": c.summary,
            "messages": [{"id": m.id, "role": m.role, "content": m.content, "meta": m.meta,
                          "created_at": m.created_at.isoformat()} for m in msgs]}


@router.delete("/conversations/{cid}")
async def delete_conversation(cid: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_session)):
    await db.execute(delete(Message).where(Message.conversation_id == cid, Message.user_id == user.id))
    await db.execute(delete(Conversation).where(Conversation.id == cid, Conversation.user_id == user.id))
    await db.commit()
    return {"ok": True}


@router.post("/feedback")
async def feedback(data: FeedbackIn, user: User = Depends(current_user)):
    """Self-Learning: corrections become lessons; admins can let ROBIN retune its own settings."""
    return await learn_from_feedback(user.id, data.message_id, data.rating, data.text,
                                     data.apply_settings and user.is_admin)


# ---------------------------------------------------------------- real-time WebSocket
ws_router = APIRouter()


@ws_router.websocket("/ws")
async def events_ws(ws: WebSocket):
    user = await ws_user(ws)
    await ws.accept()
    if not user:
        await ws.send_json({"type": "error", "error": "unauthorized"})
        await ws.close()
        return
    hub.add(user.id, ws)
    await ws.send_json({"type": "hello", "user": user.username})
    try:
        while True:
            msg = await ws.receive_json()
            if msg.get("type") == "chat":
                async def run(m=msg):
                    res = await chat(user.id, m.get("text", ""), m.get("conversation_id"), bool(m.get("voice")),
                                     channel="ws")
                    await ws.send_json({"type": "chat_reply", "ref": m.get("ref"), **res})
                asyncio.create_task(run())
            elif msg.get("type") == "ping":
                await ws.send_json({"type": "pong"})
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        hub.remove(user.id, ws)
