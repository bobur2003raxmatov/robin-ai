"""Claude Code bridge — runs the real Claude Code CLI (the same one used in the terminal) inside the ROBIN
project folder and streams its work to the Admin panel.

Rules
  • Admin only. Works ONLY while the panel icon is lit (state["enabled"] == True); otherwise every call is refused
    and no process is started.
  • "Auto memory": the session id is saved and resumed (--resume), CLAUDE.md in the project root describes ROBIN,
    and a short journal of previous Claude tasks (notes/05_Claude_jurnali.md) plus the tail of the ROBIN work log
    is appended to the system prompt, so a fresh session still remembers the code written in ROBIN.
  • One task at a time; STOP kills the whole process tree.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from backend.config import BASE_DIR, DATA_DIR

log = logging.getLogger("robin.claude")

NOTES = BASE_DIR / "notes"
JOURNAL = NOTES / "05_Claude_jurnali.md"
WORKLOG = NOTES / "01_Qilingan_ishlar.md"
MODES = ("default", "acceptEdits", "plan", "bypassPermissions")
DEFAULT_STATE = {"enabled": False, "session_id": "", "permission_mode": "acceptEdits", "model": "",
                 "history": [], "total_cost": 0.0, "runs": 0}


def _state_file() -> Path:
    from backend.security.services import CONFIG_FILE      # lives next to the DB (tests stay isolated)
    return CONFIG_FILE.parent / "claude_state.json"


def find_cli() -> str | None:
    """Prefer the native claude.exe behind the npm shim (no cmd.exe quoting problems)."""
    custom = os.environ.get("CLAUDE_CLI")
    if custom and Path(custom).exists():
        return custom
    found = shutil.which("claude")
    if found and found.lower().endswith((".cmd", ".ps1")) or (found and Path(found).suffix == ""):
        exe = Path(found).parent / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
        if exe.exists():
            return str(exe)
    if found:
        return found
    for p in (Path.home() / ".local" / "bin" / "claude.exe", Path.home() / ".local" / "bin" / "claude"):
        if p.exists():
            return str(p)
    return None


def _child_env() -> dict:
    env = {k: v for k, v in os.environ.items()
           if not (k.startswith("CLAUDE") and k != "CLAUDE_CONFIG_DIR") and k != "ANTHROPIC_API_KEY"}
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _tail(path: Path, lines: int) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8").splitlines()[-lines:])
    except OSError:
        return ""


def _short(v, n=300) -> str:
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    return s if len(s) <= n else s[:n] + "…"


class ClaudeBridge:
    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.lock = asyncio.Lock()
        self.started_at = 0.0
        self.current = ""
        self._version = ""

    # ---------------------------------------------------------------- state
    def load(self) -> dict:
        st = dict(DEFAULT_STATE)
        try:
            st.update(json.loads(_state_file().read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
        return st

    def save(self, st: dict) -> dict:
        st["history"] = st.get("history", [])[-120:]
        _state_file().write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
        return st

    def update(self, **kw) -> dict:
        st = self.load()
        st.update({k: v for k, v in kw.items() if v is not None})
        return self.save(st)

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def version(self) -> str:
        if self._version:
            return self._version
        cli = find_cli()
        if not cli:
            return ""
        try:
            out = subprocess.run([cli, "--version"], capture_output=True, text=True, timeout=20, env=_child_env(),
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self._version = (out.stdout or out.stderr).strip()[:60]
        except Exception as e:      # noqa: BLE001
            self._version = f"? ({e})"
        return self._version

    def status(self) -> dict:
        st = self.load()
        return {"enabled": st["enabled"], "running": self.running, "cli": find_cli(), "version": self.version(),
                "session_id": st["session_id"], "permission_mode": st["permission_mode"], "model": st["model"],
                "modes": list(MODES), "history": st["history"][-60:], "runs": st["runs"],
                "total_cost": round(st.get("total_cost", 0.0), 4), "current": self.current if self.running else "",
                "started_at": self.started_at if self.running else 0, "project": str(BASE_DIR)}

    # ---------------------------------------------------------------- memory
    def system_prompt(self, admin: str) -> str:
        return (
            "Sen ROBIN AI loyihasining (" + str(BASE_DIR) + ") ichida, ROBIN Admin panelidagi 'Claude' menyusidan "
            f"ishga tushirilgansan. Buyruq beruvchi: admin @{admin}. Javoblarni o'zbek tilida yoz.\n"
            "Loyiha tuzilmasi va qoidalar CLAUDE.md faylida. Har bir o'zgarishdan keyin tests/ ni ishga tushir "
            "(.venv\\Scripts\\python.exe -m pytest -q) va notes/01_Qilingan_ishlar.md ga sanali qisqa yozuv qo'sh.\n"
            "Foydalanuvchining ishlab turgan serveri :8000 portda — uni o'chirma; sinov uchun boshqa port ishlat.\n\n"
            "=== Avvalgi Claude vazifalari (avto-xotira) ===\n" + (_tail(JOURNAL, 40) or "(hali yo'q)") +
            "\n\n=== ROBIN ish jurnali (oxirgi qism) ===\n" + (_tail(WORKLOG, 50) or "(bo'sh)")
        )

    def _journal(self, admin: str, prompt: str, result: str, cost: float, ok: bool) -> None:
        try:
            NOTES.mkdir(exist_ok=True)
            if not JOURNAL.exists():
                JOURNAL.write_text("# 🤖 Claude jurnali\n\nAdmin paneldagi Claude bajargan vazifalar (avto-xotira).\n",
                                   encoding="utf-8")
            line = (f"\n## {datetime.now():%Y-%m-%d %H:%M} — @{admin} {'✅' if ok else '❌'}\n"
                    f"**Vazifa:** {_short(prompt.strip(), 400)}\n\n**Natija:** {_short((result or '').strip(), 900)}\n"
                    f"<sub>${cost:.4f}</sub>\n")
            with JOURNAL.open("a", encoding="utf-8") as f:
                f.write(line)
        except OSError as e:
            log.warning("Claude jurnali yozilmadi: %s", e)

    # ---------------------------------------------------------------- run
    @staticmethod
    def parse(obj: dict) -> list[dict]:
        t = obj.get("type")
        out: list[dict] = []
        if t == "system" and obj.get("subtype") == "init":
            out.append({"t": "init", "session_id": obj.get("session_id", ""), "model": obj.get("model", "")})
        elif t == "assistant":
            for b in (obj.get("message") or {}).get("content") or []:
                if b.get("type") == "text" and b.get("text", "").strip():
                    out.append({"t": "text", "text": b["text"]})
                elif b.get("type") == "tool_use":
                    inp = b.get("input") or {}
                    brief = inp.get("command") or inp.get("file_path") or inp.get("pattern") or inp.get("description") or inp
                    out.append({"t": "tool", "name": b.get("name", ""), "input": _short(brief, 260)})
        elif t == "user":
            for b in (obj.get("message") or {}).get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    c = b.get("content")
                    if isinstance(c, list):
                        c = "\n".join(x.get("text", "") for x in c if isinstance(x, dict))
                    out.append({"t": "tool_result", "text": _short(c or "", 500), "is_error": bool(b.get("is_error"))})
        elif t == "result":
            out.append({"t": "result", "text": obj.get("result", ""), "is_error": bool(obj.get("is_error")),
                        "cost": obj.get("total_cost_usd") or 0, "duration_ms": obj.get("duration_ms") or 0,
                        "turns": obj.get("num_turns") or 0, "session_id": obj.get("session_id", "")})
        return out

    def _command(self, cli: str, st: dict, admin: str, resume: bool) -> list[str]:
        cmd = [cli, "-p", "--output-format", "stream-json", "--verbose",
               "--permission-mode", st["permission_mode"] if st["permission_mode"] in MODES else "acceptEdits",
               "--append-system-prompt", self.system_prompt(admin)]
        if resume and st.get("session_id"):
            cmd += ["--resume", st["session_id"]]
        if st.get("model"):
            cmd += ["--model", st["model"]]
        return cmd

    async def run(self, prompt: str, admin: str):
        """Async generator of events: init / text / tool / tool_result / result / error / done."""
        st = self.load()
        if not st["enabled"]:
            yield {"t": "error", "text": "Claude o'chiq. Avval paneldagi 🤖 ikonkani yoqing."}
            return
        cli = find_cli()
        if not cli:
            yield {"t": "error", "text": "Claude Code CLI topilmadi. O'rnatish: npm install -g @anthropic-ai/claude-code"}
            return
        if self.lock.locked():
            yield {"t": "error", "text": "Claude hozir boshqa vazifani bajaryapti. Kuting yoki STOP bosing."}
            return
        async with self.lock:
            self.current, self.started_at = prompt[:200], time.time()
            texts: list[str] = []
            result: dict | None = None
            for attempt in (1, 2):
                resume = attempt == 1
                got_any = False
                async for ev in self._spawn(self._command(cli, st, admin, resume), prompt):
                    if ev["t"] == "init":
                        got_any = True
                        st = self.update(session_id=ev["session_id"])
                    if ev["t"] == "text":
                        texts.append(ev["text"])
                    if ev["t"] == "result":
                        result = ev
                    if ev["t"] == "stderr" and resume and not got_any and "conversation" in ev["text"].lower():
                        continue
                    yield ev
                if got_any or not (resume and st.get("session_id")):
                    break
                st = self.update(session_id="")      # stale session → start a fresh one (memory comes from journal)
                yield {"t": "info", "text": "Eski sessiya topilmadi — yangi sessiya boshlandi (jurnal xotirasi bilan)."}
            final = (result or {}).get("text") or "\n".join(texts)
            ok = bool(result) and not result.get("is_error")
            cost = float((result or {}).get("cost") or 0)
            st = self.load()
            st["history"].append({"at": time.time(), "admin": admin, "prompt": prompt[:2000], "result": final[:6000],
                                  "ok": ok, "cost": cost, "seconds": round(time.time() - self.started_at, 1)})
            st["runs"] = st.get("runs", 0) + 1
            st["total_cost"] = st.get("total_cost", 0.0) + cost
            self.save(st)
            self._journal(admin, prompt, final, cost, ok)
            self.current = ""
            yield {"t": "done", "ok": ok, "text": final}

    async def _spawn(self, cmd: list[str], prompt: str):
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue()
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        try:
            self.proc = subprocess.Popen(cmd, cwd=str(BASE_DIR), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, env=_child_env(), creationflags=flags)
        except OSError as e:
            yield {"t": "error", "text": f"Claude ishga tushmadi: {e}"}
            return
        proc = self.proc

        def pump(stream, kind):
            for raw in iter(stream.readline, b""):
                loop.call_soon_threadsafe(q.put_nowait, (kind, raw.decode("utf-8", "replace").rstrip()))
            loop.call_soon_threadsafe(q.put_nowait, (kind, None))

        def feed():
            try:
                proc.stdin.write(prompt.encode("utf-8"))
                proc.stdin.close()
            except OSError:
                pass

        threading.Thread(target=feed, daemon=True).start()
        threading.Thread(target=pump, args=(proc.stdout, "out"), daemon=True).start()
        threading.Thread(target=pump, args=(proc.stderr, "err"), daemon=True).start()
        open_streams = 2
        while open_streams:
            kind, line = await q.get()
            if line is None:
                open_streams -= 1
                continue
            if not line.strip():
                continue
            if kind == "err":
                yield {"t": "stderr", "text": _short(line, 400)}
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                yield {"t": "stderr", "text": _short(line, 400)}
                continue
            for ev in self.parse(obj):
                yield ev
        await loop.run_in_executor(None, proc.wait)
        if proc.returncode not in (0, None):
            yield {"t": "info", "text": f"Jarayon {proc.returncode} kodi bilan tugadi."}
        self.proc = None

    def stop(self) -> bool:
        p = self.proc
        if not p or p.poll() is not None:
            return False
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            else:
                p.kill()
        except Exception:       # noqa: BLE001
            p.kill()
        return True

    async def ask(self, prompt: str, admin: str) -> str:
        """Non-streaming helper for the /claude chat & Telegram command."""
        final, err = "", ""
        async for ev in self.run(prompt, admin):
            if ev["t"] == "error":
                err = ev["text"]
            if ev["t"] == "done":
                final = ev["text"]
        return err or final or "(Claude javob qaytarmadi)"


bridge = ClaudeBridge()
