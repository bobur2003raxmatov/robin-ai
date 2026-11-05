"""ROBIN Desktop Agent — connects ANY laptop (Windows / macOS / Linux) to a ROBIN server.

The server sends tool calls over a WebSocket; this agent executes them locally with
backend/agents/computer.py and returns the results. Emergency abort: move the mouse
into a screen corner (pyautogui failsafe) or press Ctrl+C here.

    1) Dashboard → Settings → Qurilmalar → "Token olish"
    2) python desktop/robin_agent.py --server https://your-robin-server --token <device_token> [--widget]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import platform
import sys
import traceback
from pathlib import Path
from urllib.parse import quote

# Windows consoles often use cp1251/cp866: never crash on emoji / Uzbek letters in output.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = Path(__file__).resolve().parent
# Works both inside the project (desktop/robin_agent.py) and inside the downloaded ROBIN-Desktop package
for p in (HERE, HERE.parent):
    if (p / "backend" / "agents" / "computer.py").exists():
        sys.path.insert(0, str(p))
        break
CONFIG = HERE / "robin_config.json"   # written by Dashboard → Download App (server + device token)

from backend.agents import computer  # noqa: E402  (standalone, no server deps)

CFG = Path.home() / ".robin"
CFG.mkdir(exist_ok=True)


async def handle(ws, msg: dict) -> None:
    fn = computer.FUNCS.get(msg.get("fn", ""))
    try:
        if not fn:
            raise RuntimeError(f"Noma'lum funksiya: {msg.get('fn')}")
        print(f"→ {msg['fn']} {json.dumps(msg.get('args', {}), ensure_ascii=False)[:160]}")
        result = await asyncio.to_thread(fn, **(msg.get("args") or {}))
        await ws.send(json.dumps({"type": "result", "id": msg["id"], "ok": True, "result": result}, default=str))
    except Exception as e:
        traceback.print_exc()
        await ws.send(json.dumps({"type": "result", "id": msg["id"], "ok": False, "error": f"{type(e).__name__}: {e}"}))


async def run(server: str, token: str) -> None:
    import websockets
    url = server.replace("https://", "wss://").replace("http://", "ws://").rstrip("/")
    url += f"/ws/device?token={quote(token)}&platform={quote(platform.system() + ' ' + platform.release())}"
    backoff = 2
    while True:
        try:
            async with websockets.connect(url, max_size=32 * 1024 * 1024, ping_interval=20) as ws:
                print(f"✅ ROBIN serverga ulandi: {server}")
                backoff = 2
                async for raw in ws:
                    msg = json.loads(raw)
                    if msg.get("type") == "error":
                        print("❌", msg.get("error")); return
                    if msg.get("type") == "call":
                        asyncio.create_task(handle(ws, msg))
                    elif msg.get("type") == "chat_reply":
                        print("ROBIN:", msg.get("reply", "")[:500])
        except (OSError, Exception) as e:  # reconnect forever
            print(f"⚠️ Ulanish uzildi ({e}); {backoff}s dan keyin qayta urinaman…")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="")
    ap.add_argument("--token", default="")
    ap.add_argument("--widget", action="store_true", help="3D avatar vidjetini ham ochish")
    a = ap.parse_args()
    conf = json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}
    server = a.server or conf.get("server", "")
    tok_file = CFG / "device_token"
    token = a.token or conf.get("device_token") or (tok_file.read_text().strip() if tok_file.exists() else "")
    if not server or not token:
        sys.exit("Server manzili va qurilma tokeni kerak: Dashboard → Download App'dan paketni yuklab oling "
                 "yoki --server URL --token TOKEN bering.")
    tok_file.write_text(token)
    a.server = server
    if a.widget:
        import subprocess
        subprocess.Popen([sys.executable, str(HERE / "robin_widget.py"), "--server", server, "--device-token", token])
    try:
        asyncio.run(run(a.server, token))
    except KeyboardInterrupt:
        print("ROBIN agent to'xtatildi.")


if __name__ == "__main__":
    main()
