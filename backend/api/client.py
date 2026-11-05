"""Mijoz paneli (/panel) API: simple customer dashboard — chat, ready-made commands defined by the admin,
today's usage and limits. Admin edits the panel and commands via PUT /api/admin/config (client_panel,
client_commands)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.api.auth import user_out
from backend.memory.database import User
from backend.security.auth import current_user
from backend.security.services import SERVICES, get_policy, load_config, usage_today

router = APIRouter(prefix="/api/client", tags=["client"])


class RunIn(BaseModel):
    command_id: str
    extra: str = ""
    conversation_id: str | None = None


def _visible(cfg: dict, services: dict) -> list[dict]:
    return [c for c in cfg["client_commands"] if services.get(c.get("service") or "chat", True)]


@router.get("/panel")
async def panel(user: User = Depends(current_user)):
    cfg = load_config()
    pol = await get_policy(user.id)
    return {"user": user_out(user), "panel": cfg["client_panel"], "commands": _visible(cfg, pol["services"]),
            "usage": await usage_today(user.id), "limits": pol["limits"],
            "services": {k: {"on": v, "title": SERVICES[k]["title"]} for k, v in pol["services"].items()}}


@router.post("/run")
async def run(data: RunIn, user: User = Depends(current_user)):
    """Run one ready-made client command (its prompt + optional user text) through ROBIN."""
    from backend.agents.executor import chat
    cfg = load_config()
    if not cfg["client_panel"]["enabled"] and not user.is_admin:
        raise HTTPException(403, "Mijoz paneli administrator tomonidan o'chirilgan")
    pol = await get_policy(user.id)
    cmd = next((c for c in _visible(cfg, pol["services"]) if c["id"] == data.command_id), None)
    if not cmd:
        raise HTTPException(404, "Buyruq topilmadi yoki sizga ochiq emas")
    text = (cmd["prompt"] + (" " + data.extra.strip() if data.extra.strip() else "")).strip()
    return await chat(user.id, text, data.conversation_id, channel="panel")
