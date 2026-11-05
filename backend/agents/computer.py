"""Computer control primitives (synchronous, self-contained).

This module has NO backend imports so the same code runs:
  * inside the server when LOCAL_EXECUTION=true, and
  * inside desktop/robin_agent.py on any laptop (Windows / macOS / Linux) connected to a remote server.
Every function returns a JSON-serialisable dict.
"""
from __future__ import annotations

import base64
import io
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path

OS = platform.system()  # Windows | Darwin | Linux
TRASH = Path.home() / ".robin_trash"
_state = {"scale": 1.0}

try:
    import pyautogui
    pyautogui.FAILSAFE = True  # move mouse to a corner = emergency abort
    pyautogui.PAUSE = 0.05
except Exception:  # headless server
    pyautogui = None


def _need_gui():
    if pyautogui is None:
        raise RuntimeError("GUI boshqaruvi mavjud emas (pyautogui o'rnatilmagan yoki ekran yo'q)")


KNOWN_FOLDERS = {  # spoken / localized names → Windows shell folder value names
    "desktop": "Desktop", "ish stoli": "Desktop", "рабочий стол": "Desktop", "stol": "Desktop",
    "documents": "Personal", "hujjatlar": "Personal", "документы": "Personal", "my documents": "Personal",
    "downloads": "{374DE290-123F-4565-9164-39C4925E467B}", "yuklamalar": "{374DE290-123F-4565-9164-39C4925E467B}",
    "загрузки": "{374DE290-123F-4565-9164-39C4925E467B}",
    "pictures": "My Pictures", "rasmlar": "My Pictures", "изображения": "My Pictures",
    "music": "My Music", "musiqa": "My Music", "videos": "My Video", "videolar": "My Video",
}


def _known_folder(name: str) -> Path | None:
    """Real location of Desktop/Documents/Downloads… (handles OneDrive redirection on Windows)."""
    key = KNOWN_FOLDERS.get(name.strip().lower())
    if not key:
        return None
    if OS == "Windows":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
                p = Path(os.path.expandvars(winreg.QueryValueEx(k, key)[0]))
                if p.exists():
                    return p
        except OSError:
            pass
    default = {"Desktop": "Desktop", "Personal": "Documents", "My Pictures": "Pictures", "My Music": "Music",
               "My Video": "Videos"}.get(key, "Downloads")
    for base in (Path.home(), Path.home() / "OneDrive"):
        if (base / default).exists():
            return base / default
    return Path.home() / default


def _p(path: str) -> Path:
    """Resolve user paths: env vars, ~, known folder names ("Desktop/hisobot.xlsx"), relative → home."""
    raw = os.path.expandvars(str(path or "~").strip().strip('"'))
    p = Path(raw).expanduser()
    if p.is_absolute():
        return p
    parts = Path(raw).parts
    if parts:
        kf = _known_folder(parts[0])
        if kf:
            return kf.joinpath(*parts[1:])
    return Path.home() / p


# ============================================================ FILES
def list_dir(path: str = "~", pattern: str = "*", limit: int = 200) -> dict:
    p = _p(path)
    if not p.exists():
        raise FileNotFoundError(f"Papka topilmadi: {p}")
    if not p.is_dir():
        raise NotADirectoryError(f"Bu papka emas, fayl: {p}")
    items = []
    for c in sorted(p.glob(pattern), key=lambda x: (not x.is_dir(), x.name.lower()))[:limit]:
        try:
            st = c.stat()
            items.append({"name": c.name, "dir": c.is_dir(), "size": st.st_size,
                          "modified": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")})
        except OSError:
            continue
    return {"path": str(p.resolve()), "count": len(items), "items": items}


def read_file(path: str, max_chars: int = 30000) -> dict:
    p = _p(path)
    ext = p.suffix.lower()
    if ext in (".pdf", ".docx", ".xlsx", ".xls", ".xlsm", ".csv"):
        text = _extract(p)
    else:
        text = p.read_text(encoding="utf-8", errors="replace")
    return {"path": str(p), "chars": len(text), "truncated": len(text) > max_chars, "content": text[:max_chars]}


def _extract(p: Path) -> str:
    ext = p.suffix.lower()
    if ext == ".pdf":
        from pypdf import PdfReader
        return "\n".join((pg.extract_text() or "") for pg in PdfReader(str(p)).pages)
    if ext == ".docx":
        import docx
        return "\n".join(par.text for par in docx.Document(str(p)).paragraphs)
    import pandas as pd
    if ext == ".csv":
        return pd.read_csv(p).to_csv(index=False)
    return "\n\n".join(f"## {n}\n{df.to_csv(index=False)}" for n, df in pd.read_excel(p, sheet_name=None).items())


def write_file(path: str, content: str, append: bool = False) -> dict:
    p = _p(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if p.exists() and not append:
        backup = _backup(p)
    with open(p, "a" if append else "w", encoding="utf-8") as f:
        f.write(content)
    return {"path": str(p), "bytes": p.stat().st_size, "backup": backup}


def _backup(p: Path) -> str:
    dst = TRASH / datetime.now().strftime("%Y%m%d_%H%M%S") / p.name
    dst.parent.mkdir(parents=True, exist_ok=True)
    if p.is_dir():
        shutil.copytree(p, dst)
    else:
        shutil.copy2(p, dst)
    return str(dst)


def search_files(query: str, directory: str = "~", extensions: str = "", limit: int = 50,
                 content: bool = False) -> dict:
    root = _p(directory)
    exts = {e.strip().lower().lstrip(".") for e in extensions.split(",") if e.strip()}
    q = query.lower()
    found, scanned = [], 0
    skip = {"node_modules", ".git", "AppData", "$Recycle.Bin", "__pycache__", ".venv", "venv", "Library"}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip and not d.startswith(".")]
        for fn in filenames:
            scanned += 1
            if exts and fn.rsplit(".", 1)[-1].lower() not in exts:
                continue
            fp = Path(dirpath) / fn
            hit = q in fn.lower()
            if not hit and content and fp.suffix.lower() in (".txt", ".md", ".py", ".js", ".csv", ".json", ".html"):
                try:
                    hit = q in fp.read_text(encoding="utf-8", errors="ignore")[:200000].lower()
                except OSError:
                    pass
            if hit:
                try:
                    st = fp.stat()
                    found.append({"path": str(fp), "size": st.st_size,
                                  "modified": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")})
                except OSError:
                    continue
                if len(found) >= limit:
                    return {"results": found, "scanned": scanned}
        if scanned > 300000:
            break
    found.sort(key=lambda x: x["modified"], reverse=True)
    return {"results": found, "scanned": scanned}


def move_path(src: str, dst: str) -> dict:
    s, d = _p(src), _p(dst)
    d.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(s), str(d))
    return {"moved": str(s), "to": str(d)}


def delete_path(path: str) -> dict:
    """Reversible delete: moves the item into ~/.robin_trash (Backup & Recovery)."""
    p = _p(path)
    dst = TRASH / datetime.now().strftime("%Y%m%d_%H%M%S") / p.name
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(p), str(dst))
    return {"deleted": str(p), "recoverable_at": str(dst)}


def organize_folder(directory: str, by: str = "type") -> dict:
    """Sort files into sub-folders by type (Images, Documents, ...) or by month."""
    root = _p(directory)
    groups = {"Rasmlar": "jpg jpeg png gif bmp webp svg heic", "Hujjatlar": "pdf doc docx txt rtf odt md",
              "Jadvallar": "xls xlsx xlsm csv ods", "Taqdimotlar": "ppt pptx key", "Video": "mp4 mov avi mkv webm",
              "Audio": "mp3 wav ogg m4a flac", "Arxivlar": "zip rar 7z tar gz", "Dasturlar": "exe msi dmg pkg deb",
              "Kod": "py js ts html css json java cpp c go rs"}
    ext_map = {e: g for g, es in groups.items() for e in es.split()}
    moved = 0
    for f in root.iterdir():
        if not f.is_file():
            continue
        if by == "month":
            folder = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m")
        else:
            folder = ext_map.get(f.suffix.lower().lstrip("."), "Boshqalar")
        target = root / folder / f.name
        target.parent.mkdir(exist_ok=True)
        if not target.exists():
            shutil.move(str(f), str(target))
            moved += 1
    return {"directory": str(root), "moved": moved}


def open_path(path: str) -> dict:
    p = _p(path)
    if OS == "Windows":
        os.startfile(str(p))  # type: ignore[attr-defined]
    elif OS == "Darwin":
        subprocess.Popen(["open", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p)])
    return {"opened": str(p)}


def create_document(path: str, content: str, title: str = "") -> dict:
    """Create .docx / .xlsx / .md / .txt / .csv. For xlsx, content is JSON {sheet: [[row], ...]} or CSV text."""
    p = _p(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    ext = p.suffix.lower()
    if ext == ".docx":
        import docx
        d = docx.Document()
        if title:
            d.add_heading(title, 0)
        for block in content.split("\n"):
            if block.startswith("# "):
                d.add_heading(block[2:], 1)
            elif block.startswith("## "):
                d.add_heading(block[3:], 2)
            elif block.startswith(("- ", "* ")):
                d.add_paragraph(block[2:], style="List Bullet")
            else:
                d.add_paragraph(block)
        d.save(str(p))
    elif ext in (".xlsx", ".xlsm"):
        import pandas as pd
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            data = {"Sheet1": [r.split(",") for r in content.strip().splitlines()]}
        with pd.ExcelWriter(p, engine="openpyxl") as xw:
            for sheet, rows in data.items():
                df = pd.DataFrame(rows[1:], columns=rows[0]) if rows else pd.DataFrame()
                df.to_excel(xw, sheet_name=str(sheet)[:31], index=False)
    else:
        p.write_text((f"# {title}\n\n" if title and ext == ".md" else "") + content, encoding="utf-8")
    return {"created": str(p), "bytes": p.stat().st_size}


# ============================================================ APPS & WINDOWS
WIN_APPS = {
    "chrome": "chrome", "google chrome": "chrome", "edge": "msedge", "firefox": "firefox",
    "excel": "excel", "word": "winword", "powerpoint": "powerpnt", "outlook": "outlook",
    "notepad": "notepad", "bloknot": "notepad", "kalkulyator": "calc", "calculator": "calc", "calc": "calc",
    "explorer": "explorer", "provodnik": "explorer", "fayllar": "explorer", "paint": "mspaint",
    "cmd": "cmd", "terminal": "wt", "powershell": "powershell", "vscode": "code", "vs code": "code",
    "telegram": "telegram", "settings": "ms-settings:", "sozlamalar": "ms-settings:", "task manager": "taskmgr",
    "spotify": "spotify", "zoom": "zoom", "teams": "msteams:", "skype": "skype", "camera": "microsoft.windows.camera:",
}
MAC_APPS = {"chrome": "Google Chrome", "excel": "Microsoft Excel", "word": "Microsoft Word", "safari": "Safari",
            "terminal": "Terminal", "telegram": "Telegram", "vscode": "Visual Studio Code", "finder": "Finder",
            "calculator": "Calculator", "notes": "Notes"}


def _find_start_menu(name: str) -> str | None:
    dirs = [Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
            Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "Microsoft/Windows/Start Menu/Programs",
            Path.home() / "Desktop"]
    n = name.lower()
    best = None
    for d in dirs:
        if not d.exists():
            continue
        for lnk in d.rglob("*.lnk"):
            stem = lnk.stem.lower()
            if stem == n:
                return str(lnk)
            if n in stem and (best is None or len(stem) < len(Path(best).stem)):
                best = str(lnk)
    return best


def open_app(name: str, args: str = "") -> dict:
    n = name.strip().lower()
    if OS == "Windows":
        target = WIN_APPS.get(n)
        if target and target.endswith(":"):
            os.startfile(target)  # type: ignore[attr-defined]
            return {"opened": name, "via": target}
        lnk = None if target else _find_start_menu(n)
        if lnk:
            os.startfile(lnk)  # type: ignore[attr-defined]
            return {"opened": name, "via": lnk}
        cmd = f'start "" {target or name} {args}'.strip()
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            lnk = _find_start_menu(n)
            if lnk:
                os.startfile(lnk)  # type: ignore[attr-defined]
                return {"opened": name, "via": lnk}
            raise RuntimeError(f"Ilova topilmadi: {name} ({r.stderr.strip()[:200]})")
        return {"opened": name, "via": cmd}
    if OS == "Darwin":
        subprocess.run(["open", "-a", MAC_APPS.get(n, name)] + (args.split() if args else []), check=True)
        return {"opened": name}
    subprocess.Popen([n] + (args.split() if args else []), start_new_session=True)
    return {"opened": name}


def close_app(name: str) -> dict:
    import psutil
    n = name.lower().replace(".exe", "")
    target = WIN_APPS.get(n, n).lower()
    killed = []
    for proc in psutil.process_iter(["name", "pid"]):
        pname = (proc.info["name"] or "").lower().replace(".exe", "")
        if pname in (n, target):
            try:
                proc.terminate()
                killed.append(proc.info["pid"])
            except psutil.Error:
                pass
    return {"closed": name, "pids": killed, "ok": bool(killed)}


def list_windows() -> dict:
    try:
        import pygetwindow as gw
        wins = [{"title": w.title, "active": w.isActive, "minimized": w.isMinimized}
                for w in gw.getAllWindows() if w.title.strip()]
        return {"windows": wins[:80]}
    except Exception:
        import psutil
        return {"processes": sorted({p.info["name"] for p in psutil.process_iter(["name"]) if p.info["name"]})[:200]}


def focus_window(title: str) -> dict:
    import pygetwindow as gw
    wins = [w for w in gw.getAllWindows() if title.lower() in w.title.lower()]
    if not wins:
        raise RuntimeError(f"Oyna topilmadi: {title}")
    w = wins[0]
    if w.isMinimized:
        w.restore()
    try:
        w.activate()
    except Exception:
        _need_gui()
        w.minimize(); w.restore()
    return {"focused": w.title}


def active_window() -> str:
    try:
        import pygetwindow as gw
        w = gw.getActiveWindow()
        return w.title if w else ""
    except Exception:
        return ""


# ============================================================ MOUSE / KEYBOARD / SCREEN
def screenshot(max_width: int = 1366, region: list | None = None) -> dict:
    _need_gui()
    img = pyautogui.screenshot(region=tuple(region) if region else None)
    w, h = img.size
    scale = 1.0
    if w > max_width:
        scale = w / max_width
        img = img.resize((max_width, int(h / scale)))
    _state["scale"] = scale
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return {"image_b64": base64.b64encode(buf.getvalue()).decode(), "media_type": "image/png",
            "screen": [w, h], "image_size": list(img.size), "scale": round(scale, 4),
            "active_window": active_window(),
            "note": "Koordinatalar rasm o'lchamida beriladi; mouse_click avtomatik masshtablaydi."}


def mouse_click(x: float, y: float, button: str = "left", clicks: int = 1, image_coords: bool = True) -> dict:
    _need_gui()
    s = _state["scale"] if image_coords else 1.0
    rx, ry = int(x * s), int(y * s)
    pyautogui.click(rx, ry, clicks=clicks, button=button, interval=0.08)
    return {"clicked": [rx, ry], "button": button, "clicks": clicks}


def mouse_move(x: float, y: float, image_coords: bool = True) -> dict:
    _need_gui()
    s = _state["scale"] if image_coords else 1.0
    pyautogui.moveTo(int(x * s), int(y * s), duration=0.2)
    return {"moved": [int(x * s), int(y * s)]}


def drag(x1: float, y1: float, x2: float, y2: float, image_coords: bool = True) -> dict:
    _need_gui()
    s = _state["scale"] if image_coords else 1.0
    pyautogui.moveTo(int(x1 * s), int(y1 * s))
    pyautogui.dragTo(int(x2 * s), int(y2 * s), duration=0.4)
    return {"dragged": [[x1, y1], [x2, y2]]}


def type_text(text: str, enter: bool = False) -> dict:
    _need_gui()
    if text.isascii():
        pyautogui.write(text, interval=0.01)
    else:  # Unicode (o'zbek ʻ, kirill ...) → via clipboard
        import pyperclip
        old = None
        try:
            old = pyperclip.paste()
        except Exception:
            pass
        pyperclip.copy(text)
        pyautogui.hotkey("command" if OS == "Darwin" else "ctrl", "v")
        time.sleep(0.15)
        if old is not None:
            try:
                pyperclip.copy(old)
            except Exception:
                pass
    if enter:
        pyautogui.press("enter")
    return {"typed": len(text), "enter": enter}


def hotkey(keys: str) -> dict:
    """keys like 'ctrl+s', 'alt+tab', 'win+d'."""
    _need_gui()
    parts = [k.strip().lower().replace("win", "winleft") if k.strip().lower() == "win" else k.strip().lower()
             for k in keys.split("+")]
    pyautogui.hotkey(*parts)
    return {"hotkey": keys}


def press_key(key: str, times: int = 1) -> dict:
    _need_gui()
    pyautogui.press(key, presses=times, interval=0.05)
    return {"pressed": key, "times": times}


def scroll(amount: int = -5) -> dict:
    _need_gui()
    pyautogui.scroll(amount * 100)
    return {"scrolled": amount}


def wait(seconds: float = 1.0) -> dict:
    time.sleep(min(float(seconds), 60))
    return {"waited": seconds}


def clipboard_get() -> dict:
    import pyperclip
    return {"text": pyperclip.paste()[:20000]}


def clipboard_set(text: str) -> dict:
    import pyperclip
    pyperclip.copy(text)
    return {"ok": True}


def open_url(url: str) -> dict:
    if not re.match(r"^https?://", url):
        url = "https://" + url
    webbrowser.open(url)
    return {"opened": url}


def media_control(action: str) -> dict:
    """play_pause | next | prev | volume_up | volume_down | mute"""
    _need_gui()
    keymap = {"play_pause": "playpause", "next": "nexttrack", "prev": "prevtrack",
              "volume_up": "volumeup", "volume_down": "volumedown", "mute": "volumemute"}
    pyautogui.press(keymap.get(action, action))
    return {"media": action}


# ============================================================ SHELL & SANDBOX
def run_shell(command: str, timeout: int = 120, cwd: str = "~") -> dict:
    shell_cmd = ["powershell", "-NoProfile", "-Command", command] if OS == "Windows" else ["bash", "-lc", command]
    r = subprocess.run(shell_cmd, capture_output=True, text=True, timeout=timeout, cwd=str(_p(cwd)),
                       encoding="utf-8", errors="replace")
    return {"exit_code": r.returncode, "stdout": r.stdout[-15000:], "stderr": r.stderr[-5000:]}


def run_python(code: str, timeout: int = 120, workdir: str = "") -> dict:
    """Sandbox: isolated interpreter (-I), throw-away working dir, minimal env, time limit."""
    wd = Path(workdir).expanduser() if workdir else Path(tempfile.mkdtemp(prefix="robin_sbx_"))
    script = wd / "_robin_task.py"
    script.write_text(code, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k.upper() in ("PATH", "SYSTEMROOT", "TEMP", "TMP", "HOME",
                                                               "USERPROFILE", "LANG", "PYTHONIOENCODING")}
    env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run([sys.executable, "-I", str(script)], capture_output=True, text=True, timeout=timeout,
                       cwd=str(wd), env=env, encoding="utf-8", errors="replace")
    files = [str(f) for f in wd.iterdir() if f.name != script.name][:50]
    return {"exit_code": r.returncode, "stdout": r.stdout[-15000:], "stderr": r.stderr[-6000:],
            "workdir": str(wd), "files": files}


# ============================================================ SYSTEM
def system_resources() -> dict:
    import psutil
    vm = psutil.virtual_memory()
    du = psutil.disk_usage(str(Path.home().anchor or "/"))
    net = psutil.net_io_counters()
    bat = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
    top = sorted(psutil.process_iter(["name", "memory_percent"]),
                 key=lambda p: p.info.get("memory_percent") or 0, reverse=True)[:5]
    return {"cpu_percent": psutil.cpu_percent(interval=0.3), "cpu_count": psutil.cpu_count(),
            "ram_percent": vm.percent, "ram_used_gb": round(vm.used / 1e9, 2), "ram_total_gb": round(vm.total / 1e9, 2),
            "disk_percent": du.percent, "disk_free_gb": round(du.free / 1e9, 1),
            "net_sent_mb": round(net.bytes_sent / 1e6, 1), "net_recv_mb": round(net.bytes_recv / 1e6, 1),
            "battery": {"percent": bat.percent, "plugged": bat.power_plugged} if bat else None,
            "top_memory": [{"name": p.info["name"], "mem_pct": round(p.info["memory_percent"] or 0, 1)} for p in top],
            "platform": f"{OS} {platform.release()}", "hostname": platform.node()}


def security_scan() -> dict:
    """Defensive scan: suspicious process locations, listening ports, external connections, autostart entries."""
    import psutil
    findings = []
    sus_dirs = ("\\appdata\\local\\temp", "/tmp/", "\\downloads\\", "\\public\\")
    for p in psutil.process_iter(["pid", "name", "exe", "cpu_percent"]):
        exe = (p.info.get("exe") or "").lower()
        if exe and any(d in exe for d in sus_dirs):
            findings.append({"type": "process_location", "risk": "medium", "pid": p.info["pid"],
                             "name": p.info["name"], "exe": p.info["exe"]})
    listening, external = [], []
    try:
        for c in psutil.net_connections(kind="inet"):
            try:
                name = psutil.Process(c.pid).name() if c.pid else "?"
            except psutil.Error:
                name = "?"
            if c.status == "LISTEN":
                listening.append({"port": c.laddr.port, "process": name})
            elif c.raddr and c.status == "ESTABLISHED":
                external.append({"remote": f"{c.raddr.ip}:{c.raddr.port}", "process": name})
    except psutil.AccessDenied:
        findings.append({"type": "note", "risk": "info", "detail": "Tarmoq ulanishlari uchun admin huquqi kerak"})
    autostart = []
    if OS == "Windows":
        try:
            import winreg
            for hive, path in ((winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run"),
                               (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run")):
                try:
                    with winreg.OpenKey(hive, path) as k:
                        i = 0
                        while True:
                            try:
                                n, v, _ = winreg.EnumValue(k, i)
                                autostart.append({"name": n, "command": v})
                                if any(d in str(v).lower() for d in sus_dirs):
                                    findings.append({"type": "autostart", "risk": "high", "name": n, "command": v})
                                i += 1
                            except OSError:
                                break
                except OSError:
                    continue
        except ImportError:
            pass
    return {"findings": findings, "listening_ports": listening[:60], "external_connections": external[:80],
            "autostart": autostart, "summary": f"{len(findings)} ta e'tiborga loyiq holat topildi"}


# ============================================================ EXCEL EXPERT
def excel_analyze(path: str, sheet: str = "", top_n: int = 10) -> dict:
    """Profile an Excel/CSV file and detect data errors (sales-report oriented)."""
    import numpy as np
    import pandas as pd
    p = _p(path)
    if p.suffix.lower() == ".csv":
        sheets = {"csv": pd.read_csv(p)}
    else:
        sheets = pd.read_excel(p, sheet_name=sheet or None)
        if isinstance(sheets, pd.DataFrame):
            sheets = {sheet: sheets}
    report = {"file": str(p), "sheets": {}}
    formula_errors = []
    if p.suffix.lower() in (".xlsx", ".xlsm"):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(p, data_only=True, read_only=True)
            for ws in wb.worksheets:
                for row in ws.iter_rows():
                    for cell in row:
                        if isinstance(cell.value, str) and cell.value.startswith("#") and cell.value.endswith(("!", "?", "A")):
                            formula_errors.append(f"{ws.title}!{cell.coordinate}={cell.value}")
                            if len(formula_errors) > 100:
                                break
        except Exception:
            pass
    for name, df in sheets.items():
        df = df.dropna(how="all").dropna(axis=1, how="all")
        issues = []
        nulls = df.isna().sum()
        for col, n in nulls[nulls > 0].items():
            issues.append({"type": "bo'sh qiymat", "column": str(col), "count": int(n)})
        dups = int(df.duplicated().sum())
        if dups:
            issues.append({"type": "takroriy qator", "count": dups,
                           "rows": [int(i) + 2 for i in df[df.duplicated()].index[:20]]})
        num = df.select_dtypes(include=[np.number])
        stats = {}
        for col in num.columns:
            s = num[col].dropna()
            if s.empty:
                continue
            stats[str(col)] = {"sum": float(s.sum()), "mean": round(float(s.mean()), 4), "min": float(s.min()),
                               "max": float(s.max())}
            low = str(col).lower()
            if any(k in low for k in ("qty", "miqdor", "soni", "price", "narx", "summa", "amount", "total", "jami",
                                       "count", "количество", "цена", "сумма")):
                neg = s[s < 0]
                if len(neg):
                    issues.append({"type": "manfiy qiymat", "column": str(col), "count": int(len(neg)),
                                   "rows": [int(i) + 2 for i in neg.index[:20]]})
            if len(s) > 8:
                q1, q3 = s.quantile(0.25), s.quantile(0.75)
                iqr = q3 - q1
                if iqr > 0:
                    out = s[(s < q1 - 3 * iqr) | (s > q3 + 3 * iqr)]
                    if len(out):
                        issues.append({"type": "g'ayrioddiy qiymat (outlier)", "column": str(col),
                                       "count": int(len(out)), "rows": [int(i) + 2 for i in out.index[:20]]})
        # text in numeric-looking columns
        for col in df.columns:
            if df[col].dtype == object:
                conv = pd.to_numeric(df[col], errors="coerce")
                ratio = conv.notna().mean()
                if 0.6 < ratio < 1:
                    bad = df[col][conv.isna() & df[col].notna()]
                    issues.append({"type": "raqamli ustunda matn", "column": str(col), "count": int(len(bad)),
                                   "examples": [str(v) for v in bad.head(5)]})
        # qty * price == total consistency
        cols = {str(c).lower(): c for c in df.columns}
        qc = next((cols[c] for c in cols if any(k in c for k in ("qty", "miqdor", "soni", "quantity", "количество"))), None)
        pc = next((cols[c] for c in cols if any(k in c for k in ("price", "narx", "цена"))), None)
        tc = next((cols[c] for c in cols if any(k in c for k in ("total", "jami", "summa", "amount", "сумма"))), None)
        if qc is not None and pc is not None and tc is not None:
            try:
                calc = pd.to_numeric(df[qc], errors="coerce") * pd.to_numeric(df[pc], errors="coerce")
                diff = (calc - pd.to_numeric(df[tc], errors="coerce")).abs()
                bad = diff[diff > 0.01]
                if len(bad):
                    issues.append({"type": "hisob mos emas (miqdor×narx≠jami)", "columns": [str(qc), str(pc), str(tc)],
                                   "count": int(len(bad)), "rows": [int(i) + 2 for i in bad.index[:20]]})
            except Exception:
                pass
        # group summaries for categorical columns (sales by product/region/manager)
        groups = {}
        cat_cols = [c for c in df.columns if df[c].dtype == object and 1 < df[c].nunique() <= 200][:3]
        main_num = tc if tc is not None else (num.columns[0] if len(num.columns) else None)
        if main_num is not None:
            for c in cat_cols:
                g = df.groupby(c)[main_num].sum(numeric_only=True).sort_values(ascending=False)
                groups[str(c)] = {str(k): float(v) for k, v in g.head(top_n).items()}
        report["sheets"][str(name)] = {
            "rows": int(len(df)), "columns": [str(c) for c in df.columns],
            "dtypes": {str(c): str(t) for c, t in df.dtypes.items()},
            "preview": df.head(8).astype(str).values.tolist(), "numeric_stats": stats,
            "group_totals": groups, "issues": issues}
    report["formula_errors"] = formula_errors[:100]
    report["total_issues"] = sum(len(s["issues"]) for s in report["sheets"].values()) + len(formula_errors)
    return report


def excel_query(path: str, operation: str, sheet: str = "", column: str = "", by: str = "",
                filter_expr: str = "", limit: int = 50) -> dict:
    """Safe data operations: head | describe | groupby_sum | groupby_mean | filter | sort | value_counts | pivot."""
    import pandas as pd
    p = _p(path)
    df = pd.read_csv(p) if p.suffix.lower() == ".csv" else pd.read_excel(p, sheet_name=sheet or 0)
    if filter_expr:
        if re.search(r"__|import|lambda|eval|exec|open\(|@", filter_expr):
            raise ValueError("Ruxsat etilmagan filter ifodasi")
        df = df.query(filter_expr, engine="python")
    op = operation.lower()
    if op == "head":
        out = df.head(limit)
    elif op == "describe":
        out = df.describe(include="all").reset_index()
    elif op in ("groupby_sum", "groupby_mean", "groupby_count"):
        agg = op.split("_")[1]
        out = getattr(df.groupby(by)[column] if column else df.groupby(by), agg)(numeric_only=True) \
            if agg != "count" else df.groupby(by).size()
        out = out.reset_index().sort_values(out.reset_index().columns[-1], ascending=False).head(limit)
    elif op == "sort":
        out = df.sort_values(column, ascending=False).head(limit)
    elif op == "value_counts":
        out = df[column].value_counts().head(limit).reset_index()
    elif op == "pivot":
        cols = [c.strip() for c in by.split(",")]
        out = pd.pivot_table(df, index=cols[0], columns=cols[1] if len(cols) > 1 else None, values=column,
                             aggfunc="sum").reset_index().head(limit)
    elif op == "filter":
        out = df.head(limit)
    else:
        raise ValueError(f"Noma'lum operatsiya: {operation}")
    out = out if isinstance(out, pd.DataFrame) else out.to_frame()
    return {"rows": int(len(out)), "columns": [str(c) for c in out.columns],
            "data": out.astype(str).values.tolist()[:limit]}


def excel_report(path: str, output: str, title: str = "ROBIN hisobot", group_by: str = "", value: str = "",
                 notes: str = "") -> dict:
    """Build an Excel report: summary sheet + grouped totals + bar chart + data errors sheet."""
    import pandas as pd
    from openpyxl import load_workbook
    from openpyxl.chart import BarChart, Reference
    from openpyxl.styles import Font, PatternFill
    analysis = excel_analyze(path)
    p = _p(path)
    df = pd.read_csv(p) if p.suffix.lower() == ".csv" else pd.read_excel(p)
    out = _p(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out, engine="openpyxl") as xw:
        pd.DataFrame({"Ko'rsatkich": ["Fayl", "Qatorlar", "Topilgan xatolar", "Izoh"],
                      "Qiymat": [str(p.name), len(df), analysis["total_issues"], notes]}).to_excel(
            xw, sheet_name="Xulosa", index=False, startrow=2)
        if group_by and value and group_by in df.columns and value in df.columns:
            g = df.groupby(group_by)[value].sum(numeric_only=True).sort_values(ascending=False).reset_index()
            g.to_excel(xw, sheet_name="Guruhlar", index=False)
        rows = []
        for sh, info in analysis["sheets"].items():
            for iss in info["issues"]:
                rows.append({"Varaq": sh, "Turi": iss["type"], "Ustun": iss.get("column", ", ".join(iss.get("columns", []))),
                             "Soni": iss.get("count", ""), "Qatorlar": ", ".join(map(str, iss.get("rows", [])))})
        for fe in analysis["formula_errors"]:
            rows.append({"Varaq": fe.split("!")[0], "Turi": "formula xatosi", "Ustun": fe, "Soni": 1, "Qatorlar": ""})
        pd.DataFrame(rows or [{"Turi": "Xato topilmadi"}]).to_excel(xw, sheet_name="Xatolar", index=False)
        df.to_excel(xw, sheet_name="Ma'lumot", index=False)
    wb = load_workbook(out)
    ws = wb["Xulosa"]
    ws["A1"] = title
    ws["A1"].font = Font(size=16, bold=True, color="1F4E79")
    for ws_ in wb.worksheets:
        for c in ws_[3 if ws_.title == "Xulosa" else 1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="1F4E79")
        for col in ws_.columns:
            ws_.column_dimensions[col[0].column_letter].width = min(45, max(10, max(len(str(c.value or "")) for c in col[:200]) + 2))
    if "Guruhlar" in wb.sheetnames:
        gs = wb["Guruhlar"]
        ch = BarChart()
        ch.title = f"{value} — {group_by} bo'yicha"
        n = min(gs.max_row, 26)
        ch.add_data(Reference(gs, min_col=2, min_row=1, max_row=n), titles_from_data=True)
        ch.set_categories(Reference(gs, min_col=1, min_row=2, max_row=n))
        ch.width, ch.height = 22, 12
        gs.add_chart(ch, "D2")
    wb.save(out)
    return {"report": str(out), "issues": analysis["total_issues"], "sheets": wb.sheetnames}


def excel_write_cells(path: str, sheet: str, cells: dict) -> dict:
    """Write values/formulas into cells, e.g. {"D2": "=B2*C2", "A1": "Jami"}. Backup is made first."""
    from openpyxl import Workbook, load_workbook
    p = _p(path)
    backup = _backup(p) if p.exists() else None
    wb = load_workbook(p) if p.exists() else Workbook()
    ws = wb[sheet] if sheet in wb.sheetnames else wb.create_sheet(sheet)
    for ref, val in cells.items():
        ws[ref] = val
    wb.save(p)
    return {"path": str(p), "written": len(cells), "backup": backup}


# ============================================================ RECORDER (smart command learning)
class Recorder:
    """Watches the owner's actions (clicks, keys, active windows, periodic screenshots)."""

    def __init__(self) -> None:
        self.events: list[dict] = []
        self.running = False
        self._listeners = []
        self._t0 = 0.0
        self._buf = ""
        self._snap_thread = None

    def _ev(self, kind: str, **data):
        self.events.append({"t": round(time.time() - self._t0, 2), "kind": kind, "window": active_window(), **data})

    def start(self) -> dict:
        from pynput import keyboard, mouse
        self.events, self.running, self._t0, self._buf = [], True, time.time(), ""

        def on_click(x, y, button, pressed):
            if pressed and self.running:
                self._flush()
                self._ev("click", x=int(x), y=int(y), button=str(button).split(".")[-1])

        def on_press(key):
            if not self.running:
                return
            try:
                ch = key.char
            except AttributeError:
                ch = None
            if ch:
                self._buf += ch
            else:
                name = str(key).split(".")[-1]
                if name == "space":
                    self._buf += " "
                elif name == "backspace":
                    self._buf = self._buf[:-1]
                else:
                    self._flush()
                    self._ev("key", key=name)

        self._listeners = [mouse.Listener(on_click=on_click), keyboard.Listener(on_press=on_press)]
        for l in self._listeners:
            l.start()

        def snaps():
            last_title = None
            while self.running:
                title = active_window()
                if title != last_title:
                    self._ev("window_change", title=title)
                    last_title = title
                time.sleep(1.0)
        self._snap_thread = threading.Thread(target=snaps, daemon=True)
        self._snap_thread.start()
        return {"recording": True}

    def _flush(self):
        if self._buf:
            self._ev("type", text=self._buf)
            self._buf = ""

    def stop(self) -> dict:
        self._flush()
        self.running = False
        for l in self._listeners:
            l.stop()
        return {"recording": False, "events": self.events[-800:], "duration": round(time.time() - self._t0, 1)}


recorder = Recorder()


def record_start() -> dict:
    return recorder.start()


def record_stop() -> dict:
    return recorder.stop()


# Registry of everything callable remotely by the server (desktop agent uses this too)
FUNCS = {f.__name__: f for f in [
    list_dir, read_file, write_file, search_files, move_path, delete_path, organize_folder, open_path,
    create_document, open_app, close_app, list_windows, focus_window, screenshot, mouse_click, mouse_move, drag,
    type_text, hotkey, press_key, scroll, wait, clipboard_get, clipboard_set, open_url, media_control, run_shell,
    run_python, system_resources, security_scan, excel_analyze, excel_query, excel_report, excel_write_cells,
    record_start, record_stop,
]}
