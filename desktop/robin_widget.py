"""ROBIN desktop widget — small always-on-top 3D avatar in the corner of the laptop screen.

    python desktop/robin_widget.py [--server http://127.0.0.1:8000] [--corner bottom-right] [--size 180]

First run asks for your ROBIN login once; the token is stored in ~/.robin/token.
Click the robot to speak, right-click to type.
"""
from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

import httpx

# Windows consoles often use cp1251/cp866: never crash on emoji / Uzbek letters in output.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

CFG = Path.home() / ".robin"
CFG.mkdir(exist_ok=True)
TOKEN_FILE = CFG / "token"


def get_token(server: str, device_token: str = "") -> str:
    if device_token:  # pre-configured package: trade the device token for a login token (no password prompt)
        r = httpx.post(f"{server}/api/devices/session", json={"device_token": device_token}, timeout=15)
        if r.status_code == 200:
            tok = r.json()["token"]
            TOKEN_FILE.write_text(tok)
            return tok
    if TOKEN_FILE.exists():
        tok = TOKEN_FILE.read_text().strip()
        r = httpx.get(f"{server}/api/auth/me", headers={"Authorization": f"Bearer {tok}"}, timeout=10)
        if r.status_code == 200:
            return tok
    print("ROBIN'ga kirish")
    username = input("Login: ").strip()
    password = getpass.getpass("Parol: ")
    r = httpx.post(f"{server}/api/auth/login", json={"username": username, "password": password}, timeout=15)
    if r.status_code != 200:
        sys.exit(f"Kirish xatosi: {r.text}")
    tok = r.json()["token"]
    TOKEN_FILE.write_text(tok)
    return tok


def screen_size() -> tuple[int, int]:
    try:
        import pyautogui
        return pyautogui.size()
    except Exception:
        return 1920, 1080


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="")
    ap.add_argument("--device-token", default="")
    ap.add_argument("--corner", default="")
    ap.add_argument("--size", type=int, default=0)
    a = ap.parse_args()
    conf_file = Path(__file__).resolve().parent / "robin_config.json"
    conf = json.loads(conf_file.read_text(encoding="utf-8")) if conf_file.exists() else {}
    server = (a.server or conf.get("server") or "http://127.0.0.1:8000").rstrip("/")
    token = get_token(server, a.device_token or conf.get("device_token", ""))
    try:
        s = httpx.get(f"{server}/api/settings", headers={"Authorization": f"Bearer {token}"}, timeout=10).json()
        av = s.get("avatar", {})
    except Exception:
        av = {}
    corner = a.corner or av.get("widget_corner", "bottom-right")
    w = a.size or int(av.get("size", 180))
    h = int(w * 1.35)
    sw, sh = screen_size()
    margin, taskbar = 16, 56
    x = sw - w - margin if "right" in corner else margin
    y = sh - h - taskbar if "bottom" in corner else margin

    import webview
    webview.create_window("ROBIN", f"{server}/widget?token={token}", width=w, height=h, x=x, y=y,
                          frameless=True, on_top=True, transparent=True, easy_drag=True, resizable=False,
                          background_color="#000000")
    webview.start(private_mode=False)


if __name__ == "__main__":
    main()
