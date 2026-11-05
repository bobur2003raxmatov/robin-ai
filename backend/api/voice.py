from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.agents.executor import chat
from backend.ai.brain import get_brain
from backend.config import DATA_DIR
from backend.memory.database import User
from backend.memory.settings_store import get_setting
from backend.security.auth import current_user
from backend.security.services import check_limit, require_service
from backend.voice.speech_to_text import transcribe
from backend.voice.text_to_speech import prepare_uz, synthesize, voice_catalog

router = APIRouter(prefix="/api/voice", tags=["voice"])
VOICE = [Depends(require_service("voice"))]


class TTSIn(BaseModel):
    text: str
    lang: str | None = None
    overrides: dict | None = None     # try settings before saving (voice page preview)


@router.post("/tts", dependencies=VOICE)
async def tts(data: TTSIn, user: User = Depends(current_user)):
    brain = await get_brain(user.id)
    cfg = await get_setting(user.id, "voice")
    if data.overrides:
        cfg = {**cfg, **{k: v for k, v in data.overrides.items() if k != "lexicon" or isinstance(v, dict)}}
    try:
        return await synthesize(data.text, cfg, brain.keys.get("openai", ""), data.lang)
    except Exception as e:
        # Edge/OpenAI unreachable → let the browser speak (still with Uzbek text preparation)
        return {"file": None, "engine": "browser", "lang": data.lang or "uz", "error": str(e)[:200],
                "text": prepare_uz(data.text, cfg.get("lexicon") or {}) if (data.lang or "uz") == "uz" else data.text}


@router.post("/preview-text", dependencies=VOICE)
async def preview_text(data: TTSIn, user: User = Depends(current_user)):
    """Shows exactly what the Uzbek voice will read (after lexicon + numbers) — for the pronunciation editor."""
    cfg = {**(await get_setting(user.id, "voice")), **(data.overrides or {})}
    from backend.voice.text_to_speech import clean_for_speech, detect_language, prepare_text
    t = clean_for_speech(data.text, bool(cfg.get("read_code")))
    lang = data.lang or detect_language(t)
    return {"lang": lang, "spoken": prepare_text(t, lang, cfg)}


@router.get("/audio/{name}")
async def audio(name: str):
    p = (DATA_DIR / "audio" / name).resolve()
    if p.parent != (DATA_DIR / "audio").resolve() or not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="audio/mpeg", headers={"Cache-Control": "private, max-age=86400"})


@router.post("/stt", dependencies=VOICE)
async def stt(file: UploadFile = File(...), language: str = Form(""), user: User = Depends(current_user)):
    brain = await get_brain(user.id)
    cfg = await get_setting(user.id, "voice")
    try:
        return await transcribe(await file.read(), file.filename or "audio.webm", brain.keys,
                                cfg.get("stt_engine", "openai"), language or cfg.get("stt_lang", "")[:2],
                                cfg.get("stt_model", ""))
    except Exception as e:
        raise HTTPException(400, str(e)) from e


@router.post("/command", dependencies=VOICE)
async def voice_command(file: UploadFile = File(...), conversation_id: str = Form(""), language: str = Form(""),
                        user: User = Depends(current_user)):
    """One voice command → transcribe → understand → execute → spoken answer."""
    lim = await check_limit(user.id, voice=True)
    if lim:
        raise HTTPException(429, lim)
    brain = await get_brain(user.id)
    cfg = await get_setting(user.id, "voice")
    try:
        tr = await transcribe(await file.read(), file.filename or "audio.webm", brain.keys,
                              cfg.get("stt_engine", "openai"), language or cfg.get("stt_lang", "")[:2],
                              cfg.get("stt_model", ""))
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    res = await chat(user.id, tr["text"], conversation_id or None, voice_mode=True, channel="voice")
    audio = await synthesize(res["reply"], cfg, brain.keys.get("openai", ""))
    return {"transcript": tr["text"], **res, "audio": audio}


@router.get("/voices")
async def voices():
    return await voice_catalog()
