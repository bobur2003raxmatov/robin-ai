"""Admin → 🤖 Claude menu: the real Claude Code CLI working on the ROBIN code, streamed into the dashboard."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.integrations.claude_code import MODES, bridge
from backend.memory.database import User
from backend.security.auth import admin_user
from backend.security.permissions import audit

router = APIRouter(prefix="/api/claude", tags=["claude"])


class ToggleIn(BaseModel):
    enabled: bool


class ConfigIn(BaseModel):
    permission_mode: str | None = None
    model: str | None = None


class AskIn(BaseModel):
    text: str


@router.get("/status")
async def status(admin: User = Depends(admin_user)):
    return bridge.status()


@router.post("/toggle")
async def toggle(data: ToggleIn, admin: User = Depends(admin_user)):
    if not data.enabled:
        bridge.stop()
    bridge.update(enabled=data.enabled)
    await audit(admin.id, "admin:claude_" + ("on" if data.enabled else "off"), {}, actor="admin")
    return bridge.status()


@router.put("/config")
async def config(data: ConfigIn, admin: User = Depends(admin_user)):
    if data.permission_mode is not None and data.permission_mode not in MODES:
        raise HTTPException(400, "Noto'g'ri rejim")
    bridge.update(permission_mode=data.permission_mode, model=(data.model or "").strip() if data.model is not None else None)
    await audit(admin.id, "admin:claude_config", data.model_dump(exclude_none=True), actor="admin")
    return bridge.status()


@router.post("/new")
async def new_session(admin: User = Depends(admin_user)):
    if bridge.running:
        raise HTTPException(409, "Avval joriy vazifani to'xtating")
    bridge.update(session_id="")
    return bridge.status()


@router.post("/stop")
async def stop(admin: User = Depends(admin_user)):
    return {"stopped": bridge.stop()}


@router.post("/chat")
async def chat(data: AskIn, admin: User = Depends(admin_user)):
    if not data.text.strip():
        raise HTTPException(400, "Bo'sh vazifa")
    if not bridge.load()["enabled"]:
        raise HTTPException(403, "Claude o'chiq — paneldagi 🤖 ikonkani yoqing")
    if bridge.running or bridge.lock.locked():
        raise HTTPException(409, "Claude band — joriy vazifa tugashini kuting yoki STOP bosing")
    await audit(admin.id, "admin:claude_task", {"text": data.text[:300]}, actor="admin")

    async def gen():
        async for ev in bridge.run(data.text, admin.username):
            yield json.dumps(ev, ensure_ascii=False) + "\n"
    return StreamingResponse(gen(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
