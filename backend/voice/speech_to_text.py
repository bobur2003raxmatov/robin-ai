"""Speech-to-Text: OpenAI Whisper / gpt-4o-transcribe (uz/ru/en, dialects) or Gemini audio understanding.
Browser Web Speech API (uz-UZ / ru-RU / en-US) is used client-side for live conversation."""
from __future__ import annotations

import base64
import re

import httpx

HINTS = {
    "uz": ("O'zbek tilidagi nutq. Sheva so'zlari bo'lishi mumkin (Toshkent, Farg'ona, Samarqand, Xorazm). "
           "Lotin alifbosida to'g'ri imlo bilan yoz: o', g', sh, ch, q, x, h. "
           "Masalan: ROBIN, Excel, Telegram, hisobot, uchrashuv, fayl, papka."),
    "ru": "Речь на русском языке. Пиши с правильной орфографией и пунктуацией. Например: ROBIN, Excel, Telegram.",
    "en": "English speech. Proper spelling and punctuation. Names: ROBIN, Excel, Telegram.",
}
UZ_HINT = HINTS["uz"]
MIME = {"webm": "audio/webm", "wav": "audio/wav", "ogg": "audio/ogg", "oga": "audio/ogg", "mp3": "audio/mpeg",
        "m4a": "audio/mp4", "mp4": "audio/mp4", "flac": "audio/flac"}

# Frequent mis-hearings of Uzbek by generic recognisers → correct spelling.
FIXES = [(r"\bro'?bin\b|\brabin\b|\brobbin\b|\bробин\b", "ROBIN"), (r"\bekse?l\b", "Excel"),
         (r"\bo‘|o’|oʻ", "o'"), (r"g‘|g’|gʻ", "g'")]


def clean_transcript(text: str) -> str:
    t = (text or "").strip()
    for pat, rep in FIXES:
        t = re.sub(pat, rep, t, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", t)


async def transcribe(audio: bytes, filename: str, keys: dict, engine: str = "openai", language: str = "",
                     model: str = "") -> dict:
    lang = (language or "")[:2]
    hint = HINTS.get(lang, UZ_HINT)
    if engine in ("openai", "browser") and keys.get("openai") or (engine == "gemini" and not keys.get("gemini")
                                                                  and keys.get("openai")):
        m = model if model in ("whisper-1", "gpt-4o-transcribe", "gpt-4o-mini-transcribe") else "whisper-1"
        data = {"model": m, "prompt": hint, "response_format": "verbose_json" if m == "whisper-1" else "json"}
        if lang:
            data["language"] = lang
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post("https://api.openai.com/v1/audio/transcriptions",
                             headers={"Authorization": f"Bearer {keys['openai']}"},
                             files={"file": (filename, audio)}, data=data)
        r.raise_for_status()
        j = r.json()
        return {"text": clean_transcript(j.get("text", "")), "language": j.get("language", lang), "engine": m}
    if keys.get("gemini"):
        mime = MIME.get(filename.rsplit(".", 1)[-1].lower(), "audio/webm")
        body = {"contents": [{"parts": [
            {"text": "Ushbu audioni so'zma-so'z matnga aylantir (o'zbek, rus yoki ingliz). " + hint +
                     " Faqat aytilgan matnni qaytar, izoh qo'shma."},
            {"inline_data": {"mime_type": mime, "data": base64.b64encode(audio).decode()}}]}],
            "generationConfig": {"temperature": 0}}
        import time as _t

        from backend.ai.providers import GeminiProvider
        from backend.config import settings
        first = GeminiProvider.resolved.get(settings.GEMINI_MODEL, settings.GEMINI_MODEL)
        gp = GeminiProvider(keys["gemini"], first)
        errors = []
        async with httpx.AsyncClient(timeout=120) as c:
            for gm in gp._candidates(first)[:5]:     # busy / out-of-quota model (429/503) → next model
                r = await c.post(f"https://generativelanguage.googleapis.com/v1beta/models/{gm}:generateContent",
                                 headers={"x-goog-api-key": keys["gemini"]}, json=body)
                if r.status_code == 200:
                    try:
                        parts = r.json()["candidates"][0]["content"]["parts"]
                    except (KeyError, IndexError, ValueError):
                        errors.append(f"{gm}: bo'sh javob")
                        continue
                    return {"text": clean_transcript("".join(p.get("text", "") for p in parts)), "language": lang,
                            "engine": f"gemini ({gm})"}
                errors.append(f"{gm}: {r.status_code}")
                if r.status_code in (429, 503, 500, 404):
                    GeminiProvider.cooldown[gm] = _t.time() + (86400 if r.status_code == 404 else 90)
                    continue
                break
        raise RuntimeError("Gemini ovozni tanimadi: " + ", ".join(errors))
    raise RuntimeError("Server STT uchun OpenAI yoki Gemini kaliti kerak. Brauzer ovoz tanish rejimidan foydalaning.")
