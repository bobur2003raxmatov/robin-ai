"""Real-time event hub: pushes task progress, approvals, notifications and avatar states to the
user's open dashboards / desktop widgets, and forwards important ones to Telegram."""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from fastapi import WebSocket

from backend.memory.database import Notification, SessionLocal

log = logging.getLogger("robin.events")


class EventHub:
    def __init__(self) -> None:
        self.clients: dict[str, set[WebSocket]] = {}
        self.external: list[Callable[[str, str, str, str], Awaitable[None]]] = []  # telegram etc.

    def add(self, user_id: str, ws: WebSocket) -> None:
        self.clients.setdefault(user_id, set()).add(ws)

    def remove(self, user_id: str, ws: WebSocket) -> None:
        self.clients.get(user_id, set()).discard(ws)

    async def emit(self, user_id: str, type_: str, data: dict) -> None:
        dead = []
        for ws in list(self.clients.get(user_id, ())):
            try:
                await ws.send_json({"type": type_, **data})
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.remove(user_id, ws)

    async def notify(self, user_id: str, title: str, body: str = "", level: str = "info",
                     external: bool = True) -> None:
        async with SessionLocal() as db:
            db.add(Notification(user_id=user_id, level=level, title=title[:300], body=body))
            await db.commit()
        await self.emit(user_id, "notification", {"level": level, "title": title, "body": body})
        if external:
            for fn in self.external:
                try:
                    await fn(user_id, title, body, level)
                except Exception as e:  # never break the caller
                    log.debug("external notify failed: %s", e)

    async def avatar(self, user_id: str, state: str, text: str = "") -> None:
        """Avatar states: idle | listening | thinking | speaking | working | happy | warning"""
        await self.emit(user_id, "avatar", {"state": state, "text": text[:200]})


hub = EventHub()


def fire(coro) -> None:
    try:
        asyncio.get_running_loop().create_task(coro)
    except RuntimeError:
        pass
