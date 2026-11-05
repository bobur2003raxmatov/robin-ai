"""Online per-user ROBIN settings (stored in DB, editable from Dashboard, Telegram or by ROBIN itself)."""
from __future__ import annotations

import copy

from sqlalchemy import select

from backend.memory.database import SessionLocal, UserSetting
from backend.security.permissions import DEFAULT_PERMISSIONS
from backend.security.vault import decrypt, encrypt, mask

DEFAULTS: dict[str, dict] = {
    "personality": {
        "name": "ROBIN",
        "style": "do'stona, aqlli, aniq va biroz hazilkash",
        "humor": 0.4,           # 0..1
        "formality": "sen",     # sen | siz
        "emoji": False,
        "language": "auto",     # auto | uz | ru | en
    },
    "brain": {
        "providers": ["anthropic", "openai", "gemini", "groq", "cerebras", "mistral", "openrouter", "github",
                      "huggingface", "cloudflare"],   # fallback order
        "multi_brain": True,     # route to specialist agents
        "self_review": True,     # review important answers/results
        "ensemble": False,       # ask several AIs and merge (slower, costlier)
        "temperature": 0.4,
        "max_tokens": 4096,
    },
    "permissions": DEFAULT_PERMISSIONS,
    "voice": {
        # --- speaking (TTS)
        "tts_engine": "edge",    # edge | openai | browser
        "voice_uz": "uz-UZ-SardorNeural",
        "voice_ru": "ru-RU-DmitryNeural",
        "voice_en": "en-US-AndrewNeural",
        "rate": "+0%",           # -50 … +100
        "pitch": "+0Hz",         # -50 … +50
        "volume": "+0%",         # -50 … +50
        "speak_language": "auto",   # auto | uz | ru | en
        "multilingual": True,    # Russian / English sentences inside a reply get their own voice
        "speak_numbers": True,   # 15:30, 5-noyabr, 15% → Uzbek words
        "read_code": False,      # read code blocks aloud or say "(kod ekranda)"
        "max_chars": 3000,
        "auto_speak": False,     # read every chat answer aloud (voice questions are always answered by voice)
        "lexicon": {},           # user pronunciation dictionary {"Sardor": "Sardorbek", "CRM": "si-ar-em"}
        "openai_voice": "onyx",
        "openai_model": "tts-1",  # tts-1 | tts-1-hd | gpt-4o-mini-tts
        "openai_instructions": "",
        "browser_voice": "",
        # --- listening (STT)
        "stt_engine": "browser",  # browser | openai | gemini
        "stt_lang": "uz-UZ",
        "stt_model": "whisper-1",
        "wake_word": "robin",
        "require_wake": False,
        "live_conversation": True,
        "barge_in": True,        # user can interrupt ROBIN while it speaks
        "echo_filter": 0.5,      # 0..1 — how strictly ROBIN ignores its own voice from the speakers
        "silence_ms": 1500,      # live mode: pause that ends a phrase
        "noise_suppression": True,
        "chime": True,           # short sound when listening starts/stops
    },
    "avatar": {
        "color": "#3fa9ff",
        "accent": "#ffb020",
        "style": "robot",
        "widget_corner": "bottom-right",
        "size": 160,
        "eye_tracking": True,
    },
    "trading": {
        "mode": "paper",
        "max_daily_loss_pct": 3.0,
        "max_position_pct": 10.0,
        "max_risk_per_trade_pct": 1.0,
        "default_exchange": "binance",
        "level": "beginner",
    },
    "notifications": {"telegram": True, "desktop": True, "web": True},
    "smart_home": {"home_assistant_url": "", "devices": []},
}

SECRET_KEYS = {"api_keys"}  # {"anthropic": "...", "openai": "...", "gemini": "...", "binance_key": ..., ...}


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


async def get_setting(user_id: str, key: str) -> dict:
    async with SessionLocal() as db:
        row = await db.scalar(select(UserSetting).where(UserSetting.user_id == user_id, UserSetting.key == key))
    if key in SECRET_KEYS:
        if not row:
            return {}
        return {k: decrypt(v) for k, v in (row.value or {}).items()}
    out = _merge(DEFAULTS.get(key, {}), row.value if row else {})
    if key == "permissions":   # admin policy: modules of disabled services are always off
        from backend.security.services import apply_to_permissions
        out = await apply_to_permissions(user_id, out)
    return out


async def set_setting(user_id: str, key: str, value: dict, replace: bool = False) -> dict:
    async with SessionLocal() as db:
        row = await db.scalar(select(UserSetting).where(UserSetting.user_id == user_id, UserSetting.key == key))
        if key in SECRET_KEYS:
            current = dict(row.value) if row else {}
            for k, v in value.items():
                if v in (None, ""):
                    current.pop(k, None)
                else:
                    current[k] = encrypt(str(v))
            stored = current
        else:
            stored = value if (replace or not row) else _merge(row.value or {}, value)
        if row:
            row.value = stored
        else:
            db.add(UserSetting(user_id=user_id, key=key, value=stored, secret=key in SECRET_KEYS))
        await db.commit()
    return await get_setting(user_id, key)


async def all_settings(user_id: str) -> dict:
    out = {k: await get_setting(user_id, k) for k in DEFAULTS}
    keys = await get_setting(user_id, "api_keys")
    out["api_keys"] = {k: mask(v) for k, v in keys.items()}
    return out
