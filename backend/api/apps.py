"""Download App: desktop agent package (one-click, pre-configured), mobile (PWA) links and QR codes."""
from __future__ import annotations

import hashlib
import io
import json
import secrets
import socket
import time
import zipfile

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import BASE_DIR, settings
from backend.memory.database import Device, User, get_session
from backend.security.auth import create_token, current_user
from backend.security.services import require_service

router = APIRouter(tags=["apps"])
_links: dict[str, dict] = {}   # one-off download id → {user_id, device_token, base, expires}
LINK_TTL = 30 * 60

DESKTOP_REQS = """httpx>=0.27
websockets>=12
psutil>=5.9
pyautogui>=0.9.54
pyperclip>=1.8
pynput>=1.7
Pillow>=10.3
pandas>=2.2
openpyxl>=3.1
pypdf>=4.2
python-docx>=1.1
pywebview>=5.1
"""

WIN_BAT = r"""@echo off
chcp 65001 >nul
title ROBIN Desktop
cd /d %~dp0
echo ==========================================
echo   ROBIN Desktop - o'rnatish va ishga tushirish
echo ==========================================
where python >nul 2>nul
if errorlevel 1 (
  echo Python topilmadi. Python 3.10+ ni o'rnating va "Add python.exe to PATH" belgisini qo'ying.
  start https://www.python.org/downloads/
  pause
  exit /b 1
)
if not exist .venv (
  echo [1/3] Virtual muhit yaratilmoqda...
  python -m venv .venv
)
echo [2/3] Kutubxonalar o'rnatilmoqda (birinchi marta 1-3 daqiqa)...
.venv\Scripts\python -m pip install -q --upgrade pip
.venv\Scripts\python -m pip install -q -r requirements-desktop.txt
echo [3/3] ROBIN ishga tushmoqda. Bu oynani yopmang - yopsangiz ROBIN bu kompyuterni boshqara olmaydi.
.venv\Scripts\python robin_agent.py --widget
pause
"""

UNIX_SH = """#!/usr/bin/env bash
# ROBIN Desktop — macOS / Linux
set -e
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo "Python 3.10+ kerak: https://www.python.org/downloads/"; exit 1; }
[ -d .venv ] || python3 -m venv .venv
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -r requirements-desktop.txt
echo "ROBIN ishga tushmoqda (macOS: Tizim sozlamalari → Maxfiylik → Accessibility va Screen Recording ruxsatini bering)"
.venv/bin/python robin_agent.py --widget
"""

README = """ROBIN Desktop
=============

Bu paket shu kompyuterni ROBIN serveriga ulaydi: ROBIN fayllar, ilovalar, ekran, sichqoncha va
klaviatura bilan shu yerda ishlay oladi. Ekran chetida 3D robot vidjeti paydo bo'ladi.

O'RNATISH
  Windows : "ROBIN_Ornatish_Windows.bat" faylini ikki marta bosing.
  macOS   : Terminalda:  bash install_mac_linux.sh
  Linux   : bash install_mac_linux.sh

Hech narsa kiritish shart emas — server manzili va qurilma tokeni robin_config.json faylida tayyor.
Bu faylni boshqalarga bermang (u shu qurilmaga ROBIN orqali kirish huquqini beradi).

BOSHQARISH
  * Vidjetdagi robotni bosing — gapiring; o'ng tugma — yozing.
  * Favqulodda to'xtatish: sichqonchani ekranning burchagiga olib boring yoki oynada Ctrl+C.
  * Qurilmani o'chirish: Dashboard → Settings → Qurilmalar → 🗑.

Talab: Python 3.10+, internet yoki ROBIN serveri bilan bir tarmoq.
"""


def lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def qr_svg(text: str) -> str:
    import qrcode
    import qrcode.image.svg
    img = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
    return img.to_string(encoding="unicode")


def _base_urls(request: Request) -> dict:
    ip = lan_ip()
    exposed = settings.HOST in ("0.0.0.0", "::", ip)
    return {"local": str(request.base_url).rstrip("/"), "lan": f"http://{ip}:{settings.PORT}", "lan_ip": ip,
            "exposed": exposed, "host": settings.HOST, "port": settings.PORT}


class LinkIn(BaseModel):
    name: str = "Laptop"
    base: str = ""     # server URL the new device should connect to (defaults to the one in the browser)


@router.get("/api/apps/info")
async def info(request: Request, user: User = Depends(current_user)):
    u = _base_urls(request)
    mobile_url = u["lan"] + "/#home"   # phones can only reach the LAN address (needs HOST=0.0.0.0)
    return {**u, "mobile_url": mobile_url, "mobile_qr": qr_svg(mobile_url),
            "telegram": bool(settings.TELEGRAM_BOT_TOKEN), "version": settings.VERSION}


@router.post("/api/apps/desktop-link", dependencies=[Depends(require_service("devices"))])
async def desktop_link(data: LinkIn, request: Request, user: User = Depends(current_user),
                       db: AsyncSession = Depends(get_session)):
    """Registers a new device and returns a one-off 30-minute download link (+QR) of a pre-configured package."""
    token = secrets.token_urlsafe(32)
    d = Device(user_id=user.id, name=(data.name or "Laptop")[:120], token_hash=hashlib.sha256(token.encode()).hexdigest())
    db.add(d)
    await db.commit()
    base = (data.base or str(request.base_url)).rstrip("/")
    rid = secrets.token_urlsafe(18)
    _links[rid] = {"user_id": user.id, "device_token": f"{d.id}.{token}", "server": base, "expires": time.time() + LINK_TTL}
    for k in [k for k, v in _links.items() if v["expires"] < time.time()]:
        _links.pop(k, None)
    url = f"{base}/download/desktop/{rid}"
    return {"url": url, "qr": qr_svg(url), "expires_in": LINK_TTL, "device_id": d.id, "device_name": d.name}


@router.get("/download/desktop/{rid}")
async def download_desktop(rid: str):
    link = _links.get(rid)
    if not link or link["expires"] < time.time():
        raise HTTPException(410, "Havola muddati tugagan. Dashboard → Download App'dan yangisini oling.")
    buf = io.BytesIO()
    root = "ROBIN-Desktop/"
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(BASE_DIR / "desktop" / "robin_agent.py", root + "robin_agent.py")
        z.write(BASE_DIR / "desktop" / "robin_widget.py", root + "robin_widget.py")
        z.writestr(root + "backend/__init__.py", "")
        z.writestr(root + "backend/agents/__init__.py", "")
        z.write(BASE_DIR / "backend" / "agents" / "computer.py", root + "backend/agents/computer.py")
        z.writestr(root + "requirements-desktop.txt", DESKTOP_REQS)
        z.writestr(root + "robin_config.json", json.dumps({"server": link["server"], "device_token": link["device_token"]},
                                                          indent=2))
        z.writestr(root + "ROBIN_Ornatish_Windows.bat", WIN_BAT.replace("\n", "\r\n"))
        info = zipfile.ZipInfo(root + "install_mac_linux.sh")
        info.external_attr = 0o755 << 16
        z.writestr(info, UNIX_SH)
        z.writestr(root + "O'QING.txt", README)
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="ROBIN-Desktop.zip"'})


class SessionIn(BaseModel):
    device_token: str


@router.post("/api/devices/session")
async def device_session(data: SessionIn, db: AsyncSession = Depends(get_session)):
    """The desktop widget trades its device token for a normal login token (no password prompt)."""
    did, _, secret = data.device_token.partition(".")
    d = await db.get(Device, did)
    if not d or not secrets.compare_digest(d.token_hash, hashlib.sha256(secret.encode()).hexdigest()):
        raise HTTPException(401, "Qurilma tokeni yaroqsiz")
    from backend.memory.database import User as _U
    from backend.security.services import allowed, denied_text
    owner = await db.get(_U, d.user_id)
    if not owner or not owner.is_active:
        raise HTTPException(401, "Foydalanuvchi bloklangan")
    if not await allowed(d.user_id, "devices"):
        raise HTTPException(403, denied_text("devices"))
    return {"token": create_token(d.user_id, minutes=60 * 24 * 30), "device": d.name}


@router.get("/api/apps/qr")
async def qr(text: str, user: User = Depends(current_user)):
    return Response(qr_svg(text[:1000]), media_type="image/svg+xml")
