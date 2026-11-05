"""Device bridge: connects laptops running desktop/robin_agent.py (Windows/macOS/Linux) to the server.

The server sends {"id", "fn", "args"} over WebSocket, the agent executes computer.FUNCS[fn] and replies
{"id", "ok", "result"|"error"}. When no device is online and LOCAL_EXECUTION=true, tools run locally.
"""
from __future__ import annotations

import asyncio
import uuid

from fastapi import WebSocket


class DeviceBridge:
    def __init__(self) -> None:
        self.conns: dict[str, dict[str, WebSocket]] = {}   # user_id -> device_id -> ws
        self.meta: dict[str, dict] = {}                     # device_id -> info
        self.pending: dict[str, asyncio.Future] = {}
        self.preferred: dict[str, str] = {}                 # user_id -> device_id

    def register(self, user_id: str, device_id: str, ws: WebSocket, info: dict) -> None:
        self.conns.setdefault(user_id, {})[device_id] = ws
        self.meta[device_id] = {**info, "user_id": user_id}
        self.preferred.setdefault(user_id, device_id)

    def unregister(self, user_id: str, device_id: str) -> None:
        self.conns.get(user_id, {}).pop(device_id, None)
        self.meta.pop(device_id, None)
        if self.preferred.get(user_id) == device_id:
            rest = list(self.conns.get(user_id, {}))
            if rest:
                self.preferred[user_id] = rest[0]
            else:
                self.preferred.pop(user_id, None)

    def online(self, user_id: str) -> list[dict]:
        return [{"id": d, **self.meta.get(d, {})} for d in self.conns.get(user_id, {})]

    def pick(self, user_id: str, device_id: str = "") -> WebSocket | None:
        devs = self.conns.get(user_id, {})
        if device_id and device_id in devs:
            return devs[device_id]
        pref = self.preferred.get(user_id)
        return devs.get(pref) if pref else None

    async def call(self, user_id: str, fn: str, args: dict, device_id: str = "", timeout: float = 180) -> dict:
        ws = self.pick(user_id, device_id)
        if ws is None:
            raise RuntimeError("Hech qanday qurilma ulanmagan")
        rid = uuid.uuid4().hex
        fut = asyncio.get_running_loop().create_future()
        self.pending[rid] = fut
        try:
            await ws.send_json({"type": "call", "id": rid, "fn": fn, "args": args})
            return await asyncio.wait_for(fut, timeout)
        finally:
            self.pending.pop(rid, None)

    def resolve(self, msg: dict) -> None:
        fut = self.pending.get(msg.get("id", ""))
        if fut and not fut.done():
            if msg.get("ok"):
                fut.set_result(msg.get("result"))
            else:
                fut.set_exception(RuntimeError(msg.get("error", "qurilmada xato")))


bridge = DeviceBridge()
