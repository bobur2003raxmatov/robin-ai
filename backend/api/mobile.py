"""📱 ROBIN mobile app (Flutter) support: QR pairing (no password typing on the phone) and APK download.

Flow: Dashboard → Download App → "📱 Telefonni ulash" → QR {"robin":1,"server":…,"code":…}
      → phone app scans it → POST /api/mobile/pair → 30-day login token. The phone is listed under Devices;
      to revoke its token use Admin → user → "Sessiyalarni yakunlash" (ends all sessions of that user).
"""
from __future__ import annotations

import hashlib
import json
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.apps import _base_urls, qr_svg
from backend.api.auth import user_out
from backend.config import DATA_DIR, settings
from backend.memory.database import Device, User, get_session
from backend.security.auth import create_token, current_user
from backend.security.permissions import audit

router = APIRouter(tags=["mobile"])
APK = DATA_DIR / "apps" / "ROBIN.apk"
PAIR_TTL = 300
_codes: dict[str, dict] = {}


class PairIn(BaseModel):
    code: str
    device_name: str = "Telefon"


class CodeIn(BaseModel):
    server: str = ""      # address the phone should use (defaults to LAN address)


def _purge() -> None:
    for k in [k for k, v in _codes.items() if v["expires"] < time.time()]:
        _codes.pop(k, None)


@router.post("/api/mobile/pair-code")
async def pair_code(data: CodeIn, request: Request, user: User = Depends(current_user)):
    _purge()
    u = _base_urls(request)
    server = (data.server or u["lan"]).rstrip("/")      # phones can only reach the LAN address
    code = secrets.token_urlsafe(9)
    _codes[code] = {"user_id": user.id, "expires": time.time() + PAIR_TTL}
    payload = json.dumps({"robin": 1, "server": server, "code": code}, separators=(",", ":"))
    return {"code": code, "server": server, "payload": payload, "qr": qr_svg(payload), "expires_in": PAIR_TTL,
            "lan_ok": u["exposed"]}


@router.post("/api/mobile/pair")
async def pair(data: PairIn, db: AsyncSession = Depends(get_session)):
    _purge()
    entry = _codes.pop(data.code.strip(), None)
    if not entry:
        raise HTTPException(401, "Kod yaroqsiz yoki muddati tugagan. Dashboard'da yangi QR oling.")
    user = await db.get(User, entry["user_id"])
    if not user or not user.is_active:
        raise HTTPException(403, "Hisob bloklangan")
    d = Device(user_id=user.id, name=("📱 " + (data.device_name or "Telefon"))[:120],
               token_hash=hashlib.sha256(secrets.token_bytes(16)).hexdigest())
    db.add(d)
    await db.commit()
    await audit(user.id, "mobile_paired", {"device": d.name}, actor="user")
    return {"token": create_token(user.id, minutes=60 * 24 * 30), "user": user_out(user), "device_id": d.id}


@router.get("/api/mobile/info")
async def info():
    ok = APK.exists()
    return {"apk": ok, "size": APK.stat().st_size if ok else 0, "updated": APK.stat().st_mtime if ok else 0,
            "url": "/download/ROBIN.apk", "version": settings.VERSION}


@router.get("/download/ROBIN.apk")
async def apk():
    if not APK.exists():
        raise HTTPException(404, "APK hali yig'ilmagan")
    return FileResponse(APK, media_type="application/vnd.android.package-archive", filename="ROBIN.apk")
