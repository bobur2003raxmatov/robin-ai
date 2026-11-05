"""Admin policy: which ROBIN services each user may use, daily usage limits, registration control.

Stored per user in UserSetting(key="admin_policy") — users can NOT edit it themselves (the generic
/api/settings/{key} endpoint only accepts keys from settings_store.DEFAULTS). Server-wide defaults
(registration open/closed, defaults for new users) live in database/admin_config.json.

Enforcement points:
  • API routes          → Depends(require_service("trading")) …
  • Agent tools         → settings_store.get_setting(uid, "permissions") returns the *effective* permissions
                          (modules of disabled services are forced off), so tools disappear from the AI too
  • executor.chat()     → chat / voice / telegram / autopilot checks + daily message limit (all channels)
  • Dashboard           → pages of disabled services are hidden (GET /api/settings → "policy")
Admins always keep full access (an admin can't lock themselves out).
"""
from __future__ import annotations

import copy
import json
import time
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from sqlalchemy import func, select

from backend.config import DATA_DIR
from backend.memory.database import Message, SessionLocal, User, UserSetting

# id → (title, description, permission modules governed by this service)
SERVICES: dict[str, dict] = {
    "chat":         {"title": "💬 Chat va AI suhbat", "desc": "ROBIN bilan matnli suhbat (barcha kanallar)", "modules": []},
    "voice":        {"title": "🎙️ Ovoz", "desc": "Gapirish (TTS), tinglash (STT), Live suhbat", "modules": []},
    "autopilot":    {"title": "🚀 Autopilot", "desc": "Murakkab vazifalarni navbatda bajarish", "modules": []},
    "files":        {"title": "📂 Fayllar", "desc": "Fayllarni o'qish, yozish, o'chirish", "modules": ["files_read", "files_write", "files_delete"]},
    "computer":     {"title": "🖱️ Kompyuter boshqaruvi", "desc": "Dasturlar, sichqoncha/klaviatura, ekranni ko'rish", "modules": ["apps", "mouse_keyboard", "screen_vision"]},
    "terminal":     {"title": "⌨️ Terminal va Python", "desc": "Shell buyruqlari va Python sandbox", "modules": ["shell", "python"]},
    "web":          {"title": "🌐 Internet", "desc": "Qidiruv va sahifalarni o'qish", "modules": ["web"]},
    "messages":     {"title": "✉️ Xabar yuborish", "desc": "Email / xabar yuborish", "modules": ["email_messages"]},
    "memory":       {"title": "🗂️ Xotira va bilimlar", "desc": "Memory, Knowledge Center, hujjat yuklash", "modules": []},
    "commands":     {"title": "⚙️ Buyruqlar (Automation)", "desc": "Saqlangan buyruqlar, yozib olish, jadval", "modules": []},
    "reminders":    {"title": "📅 Eslatmalar", "desc": "Daily Manager, uchrashuvlar", "modules": []},
    "notes":        {"title": "📝 Notes", "desc": "Qaydlar bo'limi", "modules": []},
    "trading":      {"title": "📈 Trading (demo)", "desc": "Tahlil, backtest, demo savdo, Akademiya", "modules": ["trading_paper"]},
    "trading_live": {"title": "💰 Real trading", "desc": "Haqiqiy hisobda savdo (har doim tasdiq bilan)", "modules": ["trading_live"]},
    "smart_home":   {"title": "🏠 Aqlli uy", "desc": "Home Assistant qurilmalari", "modules": ["smart_home"]},
    "telegram":     {"title": "✈️ Telegram", "desc": "ROBIN'ni Telegram orqali boshqarish", "modules": []},
    "devices":      {"title": "💻 Qurilmalar / Download App", "desc": "Noutbuk ulash, desktop ilova yuklash", "modules": []},
    "own_keys":     {"title": "🔑 O'z AI kalitlari", "desc": "Brain sozlamalari va shaxsiy API kalitlar", "modules": []},
    "self_config":  {"title": "🧬 O'zini sozlash", "desc": "ROBIN foydalanuvchi sozlamalarini o'zi o'zgartirishi", "modules": ["self_config"]},
}
LIMITS = {"daily_messages": 0, "daily_voice": 0}           # 0 = cheklanmagan
def _config_path():
    """admin_config.json lives next to the SQLite DB (so tests / other instances never share it)."""
    from backend.config import settings
    url = settings.DATABASE_URL
    if url.startswith("sqlite") and ":///" in url:
        from pathlib import Path
        return Path(url.split(":///", 1)[1]).parent / "admin_config.json"
    return DATA_DIR / "admin_config.json"


CONFIG_FILE = _config_path()
DEFAULT_CONFIG = {"registration_open": True,
                  "default_services": {k: True for k in SERVICES},
                  "default_limits": dict(LIMITS),
                  # Mijoz paneli (/panel): oddiy foydalanuvchilar uchun alohida dashboard va tayyor buyruqlar
                  "client_panel": {"enabled": True, "default_for_users": True, "title": "ROBIN",
                                   "welcome": "Salom! Men ROBIN — sizning AI yordamchingiz. Savol bering yoki tayyor buyruqni tanlang."},
                  "client_commands": [
                      {"id": "help", "icon": "❓", "title": "Nima qila olasan?", "prompt": "Menga qanday yordam bera olasan? Qisqa ro'yxat ber."},
                      {"id": "plan", "icon": "📅", "title": "Kun rejasi", "prompt": "Bugungi kunim uchun qisqa va aniq reja tuzib ber."},
                      {"id": "translate", "icon": "🌐", "title": "Tarjima", "prompt": "Quyidagi matnni o'zbekchaga tarjima qil: "},
                      {"id": "letter", "icon": "✉️", "title": "Rasmiy xat", "prompt": "Menga rasmiy xat yozib ber. Mavzu: "},
                      {"id": "summary", "icon": "🧾", "title": "Qisqacha mazmun", "prompt": "Quyidagi matnning qisqacha mazmunini yoz: "},
                  ]}


def _clean_commands(items) -> list[dict]:
    out = []
    for i, c in enumerate(items or []):
        if not isinstance(c, dict) or not str(c.get("title", "")).strip() or not str(c.get("prompt", "")).strip():
            continue
        out.append({"id": str(c.get("id") or f"c{i}")[:40], "icon": str(c.get("icon") or "⚡")[:4],
                    "title": str(c["title"]).strip()[:60], "prompt": str(c["prompt"])[:2000],
                    "service": str(c.get("service") or "chat")[:20]})
    return out[:60]


# ------------------------------------------------------------------ server config
def load_config() -> dict:
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        cfg["registration_open"] = bool(data.get("registration_open", True))
        cfg["default_services"].update({k: bool(v) for k, v in (data.get("default_services") or {}).items() if k in SERVICES})
        cfg["default_limits"].update({k: max(0, int(v or 0)) for k, v in (data.get("default_limits") or {}).items() if k in LIMITS})
        cfg["client_panel"].update({k: v for k, v in (data.get("client_panel") or {}).items() if k in cfg["client_panel"]})
        if isinstance(data.get("client_commands"), list):
            cfg["client_commands"] = _clean_commands(data["client_commands"])
    except (OSError, ValueError, TypeError):
        pass
    return cfg


def save_config(data: dict) -> dict:
    cfg = load_config()
    if "registration_open" in data:
        cfg["registration_open"] = bool(data["registration_open"])
    for k, v in (data.get("default_services") or {}).items():
        if k in SERVICES:
            cfg["default_services"][k] = bool(v)
    for k, v in (data.get("default_limits") or {}).items():
        if k in LIMITS:
            cfg["default_limits"][k] = max(0, int(v or 0))
    for k, v in (data.get("client_panel") or {}).items():
        if k in cfg["client_panel"]:
            cfg["client_panel"][k] = bool(v) if isinstance(cfg["client_panel"][k], bool) else str(v)[:500]
    if isinstance(data.get("client_commands"), list):
        cfg["client_commands"] = _clean_commands(data["client_commands"])
    CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return cfg


# ------------------------------------------------------------------ per-user policy
_cache: dict[str, tuple[float, dict]] = {}
TTL = 5.0


def _full() -> dict:
    return {"services": {k: True for k in SERVICES}, "limits": dict(LIMITS), "note": "", "tokens_after": 0,
            "is_admin": False}


async def get_policy(user_id: str) -> dict:
    hit = _cache.get(user_id)
    if hit and time.time() - hit[0] < TTL:
        return hit[1]
    pol = _full()
    async with SessionLocal() as db:
        user = await db.get(User, user_id)
        row = await db.scalar(select(UserSetting).where(UserSetting.user_id == user_id, UserSetting.key == "admin_policy"))
    stored = (row.value if row else None) or {}
    pol["services"].update({k: bool(v) for k, v in (stored.get("services") or {}).items() if k in SERVICES})
    pol["limits"].update({k: max(0, int(v or 0)) for k, v in (stored.get("limits") or {}).items() if k in LIMITS})
    pol["note"] = stored.get("note", "")
    pol["tokens_after"] = float(stored.get("tokens_after") or 0)
    if user and user.is_admin:            # admins are never restricted
        pol["services"] = {k: True for k in SERVICES}
        pol["limits"] = dict(LIMITS)
        pol["is_admin"] = True
    _cache[user_id] = (time.time(), pol)
    return pol


async def set_policy(user_id: str, services: dict | None = None, limits: dict | None = None,
                     note: str | None = None, tokens_after: float | None = None) -> dict:
    async with SessionLocal() as db:
        row = await db.scalar(select(UserSetting).where(UserSetting.user_id == user_id, UserSetting.key == "admin_policy"))
        cur = dict(row.value or {}) if row else {}
        if services is not None:
            cur["services"] = {**(cur.get("services") or {}), **{k: bool(v) for k, v in services.items() if k in SERVICES}}
        if limits is not None:
            cur["limits"] = {**(cur.get("limits") or {}), **{k: max(0, int(v or 0)) for k, v in limits.items() if k in LIMITS}}
        if note is not None:
            cur["note"] = str(note)[:500]
        if tokens_after is not None:
            cur["tokens_after"] = tokens_after
        if row:
            row.value = cur
        else:
            db.add(UserSetting(user_id=user_id, key="admin_policy", value=cur))
        await db.commit()
    _cache.pop(user_id, None)
    return await get_policy(user_id)


async def apply_defaults(user_id: str) -> None:
    """New users get the admin's default services/limits."""
    cfg = load_config()
    if all(cfg["default_services"].values()) and not any(cfg["default_limits"].values()):
        return
    await set_policy(user_id, cfg["default_services"], cfg["default_limits"])


def locked_modules(pol: dict) -> set[str]:
    return {m for sid, on in pol["services"].items() if not on for m in SERVICES[sid]["modules"]}


async def apply_to_permissions(user_id: str, perms: dict) -> dict:
    pol = await get_policy(user_id)
    for m in locked_modules(pol):
        perms[m] = False
    return perms


async def allowed(user_id: str, service: str) -> bool:
    return (await get_policy(user_id))["services"].get(service, True)


def denied_text(service: str) -> str:
    title = SERVICES.get(service, {}).get("title", service)
    return f"🔒 «{title}» xizmati siz uchun administrator tomonidan o'chirilgan."


def require_service(service: str):
    from backend.security.auth import current_user

    async def dep(user: User = Depends(current_user)) -> User:
        if not await allowed(user.id, service):
            raise HTTPException(status.HTTP_403_FORBIDDEN, denied_text(service))
        return user
    return dep


# ------------------------------------------------------------------ usage limits
def _day_start() -> datetime:
    now = datetime.now().astimezone()
    return now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


async def usage_today(user_id: str) -> dict:
    since = _day_start()
    async with SessionLocal() as db:
        msgs = await db.scalar(select(func.count()).select_from(Message).where(
            Message.user_id == user_id, Message.role == "user", Message.created_at >= since)) or 0
        rows = (await db.scalars(select(Message.meta).where(
            Message.user_id == user_id, Message.role == "user", Message.created_at >= since))).all()
    voice = sum(1 for m in rows if isinstance(m, dict) and m.get("voice"))
    return {"daily_messages": msgs, "daily_voice": voice}


async def check_limit(user_id: str, voice: bool = False) -> str | None:
    """Returns a user-facing message if today's limit is reached, else None."""
    pol = await get_policy(user_id)
    lim = pol["limits"]
    if not any(lim.values()):
        return None
    used = await usage_today(user_id)
    if lim["daily_messages"] and used["daily_messages"] >= lim["daily_messages"]:
        return (f"⏳ Bugungi limit tugadi: {lim['daily_messages']} ta xabar. Ertaga yana davom etamiz "
                f"(limitni administrator o'zgartirishi mumkin).")
    if voice and lim["daily_voice"] and used["daily_voice"] >= lim["daily_voice"]:
        return f"⏳ Bugungi ovozli so'rovlar limiti tugadi ({lim['daily_voice']} ta). Matn orqali yozishingiz mumkin."
    return None


def week_ago() -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=7)
