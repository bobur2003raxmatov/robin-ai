"""Telegram control of ROBIN: chat, voice messages, approvals (inline buttons), notifications, STOP.

Link: Dashboard → Settings → Telegram → "Kod olish", then send  /link KOD  to the bot.
"""
from __future__ import annotations

import asyncio
import io
import logging
import secrets

from sqlalchemy import select

from backend.config import settings
from backend.memory.database import SessionLocal, TelegramLink

log = logging.getLogger("robin.telegram")
_bot = None
_dp = None


async def new_link_code(user_id: str) -> str:
    code = secrets.token_hex(3).upper()
    async with SessionLocal() as db:
        db.add(TelegramLink(user_id=user_id, link_code=code))
        await db.commit()
    return code


async def chat_ids(user_id: str) -> list[str]:
    async with SessionLocal() as db:
        rows = (await db.scalars(select(TelegramLink).where(TelegramLink.user_id == user_id,
                                                            TelegramLink.chat_id != ""))).all()
    return list({r.chat_id for r in rows})


async def user_for_chat(chat_id: str) -> str | None:
    async with SessionLocal() as db:
        row = await db.scalar(select(TelegramLink).where(TelegramLink.chat_id == chat_id))
    return row.user_id if row else None


async def send_to_user(user_id: str, text: str) -> bool:
    if not _bot:
        return False
    ok = False
    for cid in await chat_ids(user_id):
        try:
            for i in range(0, len(text), 4000):
                await _bot.send_message(int(cid), text[i:i + 4000])
            ok = True
        except Exception as e:
            log.warning("telegram send failed: %s", e)
    return ok


async def send_approval(user_id: str, payload: dict) -> None:
    if not _bot:
        return
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"ap:1:{payload['id']}"),
        InlineKeyboardButton(text="❌ Rad etish", callback_data=f"ap:0:{payload['id']}")]])
    args = "\n".join(f"• {k}: {str(v)[:300]}" for k, v in (payload.get("args") or {}).items())
    for cid in await chat_ids(user_id):
        try:
            await _bot.send_message(int(cid), f"⚠️ ROBIN tasdiq so'rayapti\nAmal: {payload['tool']} "
                                              f"(xavf: {payload['risk']})\n{args}", reply_markup=kb)
        except Exception as e:
            log.warning("approval send failed: %s", e)


async def _external_notify(user_id: str, title: str, body: str, level: str) -> None:
    from backend.memory.settings_store import get_setting
    if not (await get_setting(user_id, "notifications")).get("telegram", True):
        return
    if title.startswith("Tasdiq kerak"):
        return  # sent separately with buttons
    icon = {"error": "❌", "warning": "⚠️", "success": "✅"}.get(level, "🔔")
    await send_to_user(user_id, f"{icon} {title}\n{body[:3000]}")


async def start() -> None:
    global _bot, _dp
    if not settings.TELEGRAM_BOT_TOKEN:
        return
    from aiogram import Bot, Dispatcher, F
    from aiogram.filters import Command, CommandStart
    from aiogram.types import BufferedInputFile, CallbackQuery, Message

    from backend.agents.events import hub
    from backend.agents.executor import approvals, autopilot, chat
    from backend.ai.brain import get_brain
    from backend.memory.settings_store import get_setting
    from backend.security.permissions import emergency
    from backend.voice.speech_to_text import transcribe
    from backend.voice.text_to_speech import synthesize
    from backend.config import DATA_DIR

    _bot = Bot(settings.TELEGRAM_BOT_TOKEN)
    _dp = Dispatcher()
    hub.external.append(_external_notify)

    async def link(m: Message, code: str):
        async with SessionLocal() as db:
            row = await db.scalar(select(TelegramLink).where(TelegramLink.link_code == code.strip().upper(),
                                                             TelegramLink.chat_id == ""))
            if not row:
                await m.answer("Kod noto'g'ri yoki ishlatilgan. Dashboard → Settings → Telegram'dan yangi kod oling.")
                return
            row.chat_id, row.link_code = str(m.chat.id), ""
            await db.commit()
        await m.answer("✅ ROBIN ulandi! Endi menga yozing yoki ovozli xabar yuboring.\n/stop — favqulodda to'xtatish\n"
                       "/tasks — vazifalar\n/resume — STOP'ni bekor qilish")

    @_dp.message(CommandStart())
    async def on_start(m: Message):
        parts = (m.text or "").split(maxsplit=1)
        if len(parts) == 2:
            return await link(m, parts[1])
        await m.answer("Salom! Men ROBIN 🤖. Ulash uchun: /link KOD (kodni Dashboard → Settings → Telegram'dan oling).")

    @_dp.message(Command("link"))
    async def on_link(m: Message):
        parts = (m.text or "").split(maxsplit=1)
        if len(parts) < 2:
            return await m.answer("Foydalanish: /link KOD")
        await link(m, parts[1])

    @_dp.message(Command("stop"))
    async def on_stop(m: Message):
        uid = await user_for_chat(str(m.chat.id))
        if not uid:
            return
        emergency.trigger(uid)
        n = await autopilot.cancel_all(uid)
        await m.answer(f"⛔ Favqulodda STOP. {n} ta vazifa to'xtatildi. Davom etish: /resume")

    @_dp.message(Command("resume"))
    async def on_resume(m: Message):
        uid = await user_for_chat(str(m.chat.id))
        if uid:
            emergency.release(uid)
            await m.answer("▶️ ROBIN yana ishga tayyor.")

    @_dp.message(Command("tasks"))
    async def on_tasks(m: Message):
        uid = await user_for_chat(str(m.chat.id))
        if not uid:
            return
        from backend.memory.database import Task
        async with SessionLocal() as db:
            rows = (await db.scalars(select(Task).where(Task.user_id == uid).order_by(Task.created_at.desc()).limit(10))).all()
        await m.answer("\n".join(f"[{t.status}] {t.title}" for t in rows) or "Vazifalar yo'q")

    @_dp.callback_query(F.data.startswith("ap:"))
    async def on_approval(cb: CallbackQuery):
        uid = await user_for_chat(str(cb.message.chat.id))
        _, ok, aid = cb.data.split(":", 2)
        done = uid and await approvals.decide(uid, aid, ok == "1")
        await cb.answer("Qabul qilindi" if done else "Allaqachon hal qilingan")
        await cb.message.edit_text(cb.message.text + ("\n\n✅ TASDIQLANDI" if ok == "1" else "\n\n❌ RAD ETILDI"))

    @_dp.message(F.voice | F.audio)
    async def on_voice(m: Message):
        uid = await user_for_chat(str(m.chat.id))
        if not uid:
            return await m.answer("Avval /link KOD bilan ulang.")
        f = await _bot.get_file((m.voice or m.audio).file_id)
        buf = io.BytesIO()
        await _bot.download_file(f.file_path, buf)
        brain = await get_brain(uid)
        try:
            vcfg = await get_setting(uid, "voice")
            tr = await transcribe(buf.getvalue(), "voice.ogg", brain.keys, vcfg.get("stt_engine", "openai"),
                                  vcfg.get("stt_lang", "")[:2], vcfg.get("stt_model", ""))
        except Exception as e:
            return await m.answer(f"Ovozni tanib bo'lmadi: {e}")
        await m.answer(f"🎤 {tr['text']}")
        res = await chat(uid, tr["text"], None, voice_mode=True, channel="telegram")
        await m.answer(res["reply"][:4000])
        if res["meta"].get("blocked"):
            return
        from backend.security.services import allowed
        if not await allowed(uid, "voice"):
            return
        try:
            audio = await synthesize(res["reply"], vcfg, brain.keys.get("openai", ""))
            if audio.get("file"):
                data = (DATA_DIR / "audio" / audio["file"]).read_bytes()
                try:
                    await m.answer_voice(BufferedInputFile(data, "robin.mp3"))
                except Exception:   # some clients reject MP3 as a "voice" note → send as audio
                    await m.answer_audio(BufferedInputFile(data, "ROBIN.mp3"), title="ROBIN")
        except Exception as e:
            log.debug("tts failed: %s", e)

    convs: dict[str, str] = {}

    @_dp.message(F.text)
    async def on_text(m: Message):
        uid = await user_for_chat(str(m.chat.id))
        if not uid:
            return await m.answer("Avval /link KOD bilan ulang.")
        await _bot.send_chat_action(m.chat.id, "typing")
        res = await chat(uid, m.text, convs.get(uid), channel="telegram")
        convs[uid] = res["conversation_id"]
        await m.answer(res["reply"][:4000])

    asyncio.create_task(_dp.start_polling(_bot, handle_signals=False))
    log.info("Telegram bot started")


async def stop() -> None:
    if _dp:
        try:
            await _dp.stop_polling()
        except Exception:
            pass
    if _bot:
        await _bot.session.close()
