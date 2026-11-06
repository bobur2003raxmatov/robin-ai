"""ROBIN — personal AI operating system. Server entry point.

Run:  python -m backend.main          (from the project root)
      or: uvicorn backend.main:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import asyncio
import logging
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.agents import scheduler
from backend.agents.executor import autopilot, log_error
from backend.api import admin, apps, auth, chat, claude, client, deploy, mobile, notes, robin, system, trading, voice
from backend.config import BASE_DIR, settings
from backend.integrations import telegram_bot
from backend.memory.database import init_db

import sys
# Windows consoles often use cp1251/cp866: never crash on emoji / Uzbek letters in output.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("robin")


class _RedactTokens(logging.Filter):
    """Never write login/device tokens (passed as ?token=… on WebSockets) into log files."""
    import re as _re
    _pat = _re.compile(r"(token=)[^&\s\"']+")

    def filter(self, record: logging.LogRecord) -> bool:
        if record.args:
            record.args = tuple(self._pat.sub(r"\1***", a) if isinstance(a, str) else a for a in record.args)
        if isinstance(record.msg, str):
            record.msg = self._pat.sub(r"\1***", record.msg)
        return True


for _name in ("uvicorn.access", "uvicorn.error", "uvicorn"):
    logging.getLogger(_name).addFilter(_RedactTokens())
# httpx logs every outgoing URL at INFO — some APIs carry secrets in URLs, so keep it quiet.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
FRONTEND = BASE_DIR / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    autopilot.start()
    await autopilot.restore()
    sched = asyncio.create_task(scheduler.loop())
    from backend.voice.text_to_speech import voice_catalog
    asyncio.create_task(voice_catalog())          # warm the neural-voice list so the Voice page opens instantly
    try:
        await telegram_bot.start()
    except Exception as e:
        log.warning("Telegram bot ishga tushmadi: %s", e)
    if settings.SECRET_KEY.startswith("change-me"):
        log.warning("SECRET_KEY standart qiymatda! .env faylida uzun tasodifiy kalit o'rnating.")
    log.info("ROBIN %s tayyor: http://%s:%s", settings.VERSION, settings.HOST, settings.PORT)
    yield
    sched.cancel()
    from backend.integrations.claude_code import bridge
    bridge.stop()
    await autopilot.stop()
    await telegram_bot.stop()


app = FastAPI(title="ROBIN AI", version=settings.VERSION, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    await log_error("", f"http:{request.url.path}", exc, traceback.format_exc())
    return JSONResponse({"detail": f"Ichki xato: {type(exc).__name__}: {str(exc)[:300]}"}, status_code=500)


for r in (auth.router, chat.router, chat.ws_router, voice.router, robin.router, robin.device_ws, trading.router,
          system.router, notes.router, apps.router, admin.router, claude.router, client.router, deploy.router,
          mobile.router):
    app.include_router(r)

from backend.api import bot_admin  # noqa: E402  — @duselb1bot veb adminkasi (/bot-admin)

app.include_router(bot_admin.router)

app.mount("/static", StaticFiles(directory=FRONTEND / "src"), name="static")


@app.get("/")
async def index():
    return FileResponse(FRONTEND / "pages" / "index.html")


@app.get("/panel")
async def client_panel():
    """Mijoz paneli — oddiy foydalanuvchilar uchun alohida dashboard."""
    return FileResponse(FRONTEND / "pages" / "panel.html")


@app.get("/widget")
async def widget():
    return FileResponse(FRONTEND / "pages" / "widget.html")


@app.get("/manifest.json")
async def manifest():
    return FileResponse(BASE_DIR / "mobile" / "manifest.json")


@app.get("/sw.js")
async def sw():
    return FileResponse(BASE_DIR / "mobile" / "sw.js", media_type="application/javascript")


def run() -> None:
    import uvicorn
    uvicorn.run("backend.main:app", host=settings.HOST, port=settings.PORT, reload=False)


if __name__ == "__main__":
    run()
