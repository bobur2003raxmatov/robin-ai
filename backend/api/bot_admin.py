"""Bot adminka (/bot-admin) — @duselb1bot buyruqlarini veb orqali bajarish.

Buyruqlar shu serverda BAJARILMAYDI: Telegram sessiyalari, Dusel adminka logini va Excel vositalari
noutbukda. Oqim:
  brauzer --(/bot-admin/api/send)--> navbat (inbox) --(/bot-admin/bridge/poll)--> noutbuk ko'prigi
  noutbuk botning o'z dispatcheri orqali bajaradi --(/bot-admin/bridge/events, /bridge/file)--> brauzer.

Kirish: login + parol. Ularni noutbuk ko'prigi yuboradi (/bridge/hello: login va PBKDF2 xeshi),
shuning uchun parol repoda ham, serverda ochiq holda ham saqlanmaydi.
Ko'prik tokeni = HMAC(SECRET_KEY, "bot-admin-bridge-v1") — repoga hech qanday sir yozilmaydi.
Ma'lumotlar: database/bot_admin.db (+ database/bot_admin_files/), git'ga kirmaydi.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response

from backend.config import BASE_DIR, DATA_DIR, settings

router = APIRouter(prefix="/bot-admin", tags=["bot-admin"])

DB_PATH = Path(os.getenv("BOT_ADMIN_DB") or (DATA_DIR / "bot_admin.db"))
FILES_DIR = DB_PATH.parent / "bot_admin_files"
PAGE = BASE_DIR / "frontend" / "pages" / "bot_admin.html"
COOKIE = "ba_s"
SESSION_DAYS = 14
MAX_UPLOAD = 20 * 1024 * 1024
MAX_FILES_BYTES = 150 * 1024 * 1024      # PythonAnywhere bepul diski kichik — eski fayllar o'chiriladi
FILE_DAYS = 7
MAX_EVENTS = 3000
ONLINE_SEC = 60

_lock = threading.Lock()
_wake = asyncio.Event()
_fails: dict[str, list[float]] = {}


def _key(purpose: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), purpose.encode(), hashlib.sha256).hexdigest()


def bridge_token() -> str:
    return _key("bot-admin-bridge-v1")


# ------------------------------------------------------------------ baza

def _db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS inbox (id INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT, "
              "created REAL, taken REAL)")
    c.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT, created REAL)")
    c.execute("CREATE TABLE IF NOT EXISTS files (id TEXT PRIMARY KEY, name TEXT, size INTEGER, created REAL)")
    return c


def _q(sql: str, args: tuple = (), one: bool = False):
    with _lock:
        c = _db()
        try:
            cur = c.execute(sql, args)
            rows = cur.fetchall()
            c.commit()
            return (rows[0] if rows else None) if one else rows
        finally:
            c.close()


def _meta(k: str, default=None):
    r = _q("SELECT v FROM meta WHERE k=?", (k,), one=True)
    return json.loads(r[0]) if r else default


def _set_meta(k: str, v) -> None:
    _q("INSERT INTO meta(k, v) VALUES(?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, json.dumps(v)))


def _add_event(ev: dict) -> int:
    ev = dict(ev, t=time.time())
    with _lock:
        c = _db()
        try:
            cur = c.execute("INSERT INTO events(payload, created) VALUES(?, ?)", (json.dumps(ev), ev["t"]))
            c.execute("DELETE FROM events WHERE id <= ?", (cur.lastrowid - MAX_EVENTS,))
            c.commit()
            return cur.lastrowid
        finally:
            c.close()


def _push_inbox(item: dict) -> int:
    with _lock:
        c = _db()
        try:
            cur = c.execute("INSERT INTO inbox(payload, created) VALUES(?, ?)", (json.dumps(item), time.time()))
            c.commit()
            rid = cur.lastrowid
        finally:
            c.close()
    _wake.set()
    return rid


def _save_file(name: str, data: bytes) -> dict:
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    fid = uuid.uuid4().hex
    (FILES_DIR / fid).write_bytes(data)
    name = (os.path.basename(name or "fayl") or "fayl")[:180]
    _q("INSERT INTO files(id, name, size, created) VALUES(?, ?, ?, ?)", (fid, name, len(data), time.time()))
    _cleanup_files()
    return {"id": fid, "name": name, "size": len(data)}


def _cleanup_files() -> None:
    rows = _q("SELECT id, size, created FROM files ORDER BY created DESC")
    total, eski = 0, time.time() - FILE_DAYS * 86400
    for fid, size, created in rows:
        total += size or 0
        if created < eski or total > MAX_FILES_BYTES:
            try:
                (FILES_DIR / fid).unlink(missing_ok=True)
            except OSError:
                pass
            _q("DELETE FROM files WHERE id=?", (fid,))


def _file_row(fid: str):
    if not fid or not all(ch in "0123456789abcdef" for ch in fid):
        return None
    r = _q("SELECT id, name, size FROM files WHERE id=?", (fid,), one=True)
    return r if r and (FILES_DIR / fid).exists() else None


# ------------------------------------------------------------------ kirish

def _pw_ok(password: str, stored: str) -> bool:
    """stored: 'pbkdf2_sha256$<iter>$<salt hex>$<hash hex>' (noutbuk ko'prigi yaratadi)."""
    try:
        algo, it, salt, h = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        calc = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(it)).hex()
        return hmac.compare_digest(calc, h)
    except (ValueError, AttributeError):
        return False


def _sign(login: str, exp: int, pw: str) -> str:
    return hmac.new(_key("bot-admin-session-v1").encode(), f"{login}|{exp}|{pw}".encode(), hashlib.sha256).hexdigest()


def _session_ok(request: Request) -> bool:
    cred = _meta("cred")
    raw = request.cookies.get(COOKIE) or ""
    if not cred or raw.count(".") != 1:
        return False
    exp, sig = raw.split(".")
    if not exp.isdigit() or int(exp) < time.time():
        return False
    return hmac.compare_digest(sig, _sign(cred["login"], int(exp), cred["pw"]))


def _need_session(request: Request) -> None:
    if not _session_ok(request):
        raise HTTPException(401, "Kirish talab qilinadi")


def _need_bridge(request: Request) -> None:
    if not hmac.compare_digest(request.headers.get("x-bridge-token", ""), bridge_token()):
        raise HTTPException(403, "Ko'prik tokeni noto'g'ri")
    _set_meta("last_seen", time.time())


def _ip(request: Request) -> str:
    return (request.headers.get("x-real-ip") or request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or (request.client.host if request.client else "?"))


# ------------------------------------------------------------------ sahifa

@router.get("", include_in_schema=False)
@router.get("/", include_in_schema=False)
async def page():
    return FileResponse(PAGE, headers={"Cache-Control": "no-store"})


@router.post("/api/login")
async def login(request: Request):
    ip = _ip(request)
    now = time.time()
    f = [t for t in _fails.get(ip, []) if now - t < 600]
    if len(f) >= 6:
        raise HTTPException(429, "Ko'p urinish — 10 daqiqadan keyin qayta urining")
    body = await request.json()
    cred = _meta("cred")
    if not cred:
        raise HTTPException(503, "Adminka hali sozlanmagan: noutbukdagi bot ishga tushib, ulanishi kerak")
    if not (hmac.compare_digest(str(body.get("login", "")).strip(), cred["login"])
            and _pw_ok(str(body.get("password", "")), cred["pw"])):
        _fails[ip] = f + [now]
        raise HTTPException(401, "Login yoki parol noto'g'ri")
    _fails.pop(ip, None)
    exp = int(now + SESSION_DAYS * 86400)
    r = JSONResponse({"ok": True})
    r.set_cookie(COOKIE, f"{exp}.{_sign(cred['login'], exp, cred['pw'])}", max_age=SESSION_DAYS * 86400,
                 httponly=True, samesite="strict", secure=request.url.scheme == "https"
                 or request.headers.get("x-forwarded-proto") == "https", path="/bot-admin")
    return r


@router.post("/api/logout")
async def logout():
    r = JSONResponse({"ok": True})
    r.delete_cookie(COOKIE, path="/bot-admin")
    return r


@router.get("/api/state")
async def state(request: Request, after: int = 0, catalog: int = 0):
    _need_session(request)
    rows = _q("SELECT id, payload FROM events WHERE id > ? ORDER BY id LIMIT 500", (after,))
    last_seen = _meta("last_seen", 0) or 0
    pending = _q("SELECT COUNT(*) FROM inbox WHERE taken IS NULL", one=True)[0]
    out = {"events": [dict(json.loads(p), id=i) for i, p in rows],
           "online": time.time() - last_seen < ONLINE_SEC, "last_seen": last_seen, "pending": pending,
           "last_id": _q("SELECT COALESCE(MAX(id), 0) FROM events", one=True)[0],
           "bot": _meta("bot", {})}
    if catalog:
        out["catalog"] = _meta("catalog", [])
    return out


@router.post("/api/send")
async def send(request: Request):
    _need_session(request)
    body = await request.json()
    if body.get("callback"):
        item = {"type": "callback", "data": str(body["callback"])[:64], "mid": int(body.get("mid") or 0)}
    else:
        text = str(body.get("text") or "").strip()
        if not text:
            raise HTTPException(400, "Bo'sh xabar")
        item = {"type": "text", "text": text[:4096]}
        _add_event({"type": "out", "text": item["text"]})
    return {"ok": True, "id": _push_inbox(item)}


@router.post("/api/upload")
async def upload(request: Request, file: UploadFile = File(...), caption: str = Form("")):
    _need_session(request)
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "Fayl 20 MB dan katta")
    f = _save_file(file.filename or "fayl", data)
    item = {"type": "document", "file": f, "mime": file.content_type or "", "caption": caption[:1024]}
    _add_event({"type": "out", "text": caption[:1024], "file": f})
    return {"ok": True, "id": _push_inbox(item)}


@router.get("/api/file/{fid}")
async def get_file(fid: str, request: Request):
    _need_session(request)
    row = _file_row(fid)
    if not row:
        raise HTTPException(404, "Fayl topilmadi (7 kundan eski fayllar o'chiriladi)")
    return FileResponse(FILES_DIR / row[0], filename=row[1])


@router.post("/api/clear")
async def clear(request: Request):
    _need_session(request)
    _q("DELETE FROM events")
    return {"ok": True}


# ------------------------------------------------------------------ noutbuk ko'prigi

@router.post("/bridge/hello")
async def bridge_hello(request: Request):
    _need_bridge(request)
    body = await request.json()
    if body.get("login") and str(body.get("pw", "")).startswith("pbkdf2_sha256$"):
        _set_meta("cred", {"login": str(body["login"])[:64], "pw": body["pw"]})
    if isinstance(body.get("catalog"), list):
        _set_meta("catalog", body["catalog"])
    if isinstance(body.get("bot"), dict):
        _set_meta("bot", body["bot"])
    return {"ok": True}


@router.get("/bridge/poll")
async def bridge_poll(request: Request, wait: int = 20):
    _need_bridge(request)
    deadline = time.time() + max(0, min(wait, 25))
    while True:
        if await request.is_disconnected():      # uzilgan ulanish buyruqni «yutib» yubormasin
            return Response(status_code=499)
        rows = _q("SELECT id, payload FROM inbox WHERE taken IS NULL ORDER BY id LIMIT 20")
        if rows:
            _q(f"UPDATE inbox SET taken=? WHERE id IN ({','.join('?' * len(rows))})",
               (time.time(), *[r[0] for r in rows]))
            _q("DELETE FROM inbox WHERE taken IS NOT NULL AND taken < ?", (time.time() - 86400,))
            return {"items": [dict(json.loads(p), id=i) for i, p in rows]}
        left = deadline - time.time()
        if left <= 0:
            return {"items": []}
        _wake.clear()
        try:
            await asyncio.wait_for(_wake.wait(), timeout=min(left, 5))
        except asyncio.TimeoutError:
            pass
        _set_meta("last_seen", time.time())


@router.post("/bridge/events")
async def bridge_events(request: Request):
    _need_bridge(request)
    body = await request.json()
    n = 0
    for ev in (body.get("events") or [])[:200]:
        if isinstance(ev, dict) and ev.get("type") in ("message", "edit", "delete", "toast", "status"):
            _add_event(ev)
            n += 1
    return {"ok": True, "n": n}


@router.post("/bridge/file")
async def bridge_file(request: Request, file: UploadFile = File(...)):
    _need_bridge(request)
    data = await file.read(50 * 1024 * 1024 + 1)
    if len(data) > 50 * 1024 * 1024:
        raise HTTPException(413, "Fayl juda katta")
    return _save_file(file.filename or "fayl", data)


@router.get("/bridge/file/{fid}")
async def bridge_get_file(fid: str, request: Request):
    _need_bridge(request)
    row = _file_row(fid)
    if not row:
        raise HTTPException(404, "Fayl topilmadi")
    return Response((FILES_DIR / row[0]).read_bytes(), media_type="application/octet-stream")


def make_password_hash(password: str, iterations: int = 200_000) -> str:
    """Testlar va noutbuk ko'prigi bilan bir xil format."""
    salt = secrets.token_bytes(16)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${hashlib.pbkdf2_hmac('sha256', password.encode(), salt, iterations).hex()}"
