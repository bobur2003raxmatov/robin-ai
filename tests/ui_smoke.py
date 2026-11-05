"""Browser end-to-end smoke test of the dashboard (real Edge/Chrome via Playwright).

    .venv\\Scripts\\python tests\\ui_smoke.py [--url http://127.0.0.1:8000] [--shots DIR]

Registers a throw-away user, opens every page, clicks the main buttons, sends a chat message and reports
JS console errors, failed requests and pages that did not render.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

PAGES = ["home", "chat", "autopilot", "brain", "memory", "agents", "automation", "files", "voice", "avatar",
         "trading", "trading/analysis", "trading/backtest", "trading/sim", "trading/journal", "trading/academy",
         "trading/risk", "settings", "notes", "download", "admin"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--shots", default="")
    ap.add_argument("--chat", default="Salom! 2+2 nechchi?")
    ap.add_argument("--user", default=f"ui_test_{int(time.time())}")
    ap.add_argument("--password", default="uitest12345")
    ap.add_argument("--login", action="store_true", help="existing user: log in instead of registering")
    a = ap.parse_args()
    shots = Path(a.shots) if a.shots else None
    if shots:
        shots.mkdir(parents=True, exist_ok=True)
    problems: list[str] = []
    with sync_playwright() as p:
        browser = None
        for channel in ("msedge", "chrome"):
            try:
                browser = p.chromium.launch(channel=channel, headless=True)
                break
            except Exception:
                continue
        if not browser:
            print("Brauzer topilmadi")
            return 2
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.on("console", lambda m: m.type == "error" and problems.append(f"[console] {page.url} :: {m.text}"))
        page.on("pageerror", lambda e: problems.append(f"[js-error] {page.url} :: {e}"))
        page.on("response", lambda r: r.status >= 400 and "/api/" in r.url and
                problems.append(f"[http {r.status}] {r.request.method} {r.url}"))
        page.goto(a.url)
        if not a.login:
            page.click("text=Ro'yxatdan o'tish")
            page.fill("#authForm input[name=full_name]", "UI Test")
        page.fill("#authForm input[name=username]", a.user)
        page.fill("#authForm input[name=password]", a.password)
        page.click("#authForm button.primary")
        page.wait_for_selector("#app.on", timeout=10000)
        for pg in PAGES:
            page.goto(f"{a.url}/#{pg}")
            page.wait_for_timeout(1500)
            text = page.inner_text("#view")
            if len(text.strip()) < 20:
                problems.append(f"[empty] #{pg} — sahifa chizilmadi")
            if shots:
                page.screenshot(path=str(shots / f"{pg.replace('/', '_')}.png"))
        # chat: type + Enter
        page.goto(f"{a.url}/#chat")
        page.wait_for_selector("#chatIn")
        page.fill("#chatIn", a.chat)
        page.press("#chatIn", "Enter")
        try:
            page.wait_for_function("document.querySelectorAll('#msgs .msg.assistant:not(.pending)').length >= 2 && "
                                   "!document.querySelector('#msgs .msg.pending')", timeout=120000)
            reply = page.locator("#msgs .msg.assistant").last.inner_text()
            print("CHAT REPLY:", reply[:300].replace("\n", " "))
        except Exception as e:
            problems.append(f"[chat] javob kelmadi: {e}")
        if shots:
            page.screenshot(path=str(shots / "chat_after.png"))
        # home quick input
        page.goto(f"{a.url}/#home")
        page.wait_for_selector("#homeInput")
        page.fill("#homeInput", "Kompyuter holatini ko'rsat")
        page.click("#homeSend")
        try:
            page.wait_for_function("document.querySelector('#homeReply').textContent.includes('ROBIN')", timeout=120000)
            print("HOME REPLY:", page.inner_text("#homeReply")[:200].replace("\n", " "))
        except Exception as e:
            problems.append(f"[home] javob kelmadi: {e}")
        # settings: live health panel must show a percentage
        page.goto(f"{a.url}/#settings")
        try:
            page.wait_for_function(r"(document.querySelector('#hOverall')||{textContent:''}).textContent.match(/\d+(\.\d+)?%/)", timeout=20000)
            print("HEALTH:", page.inner_text("#hOverall"), "|", page.inner_text("#hComp")[:200].replace("\n", " "))
            page.wait_for_timeout(4500)
            if shots:
                page.screenshot(path=str(shots / "settings_health.png"))
        except Exception as e:
            problems.append(f"[health] holat paneli ishlamadi: {e}")
        page.goto(f"{a.url}/#brain")
        page.wait_for_selector(".prov")
        n = page.locator(".prov").count()
        if n < 10:
            problems.append(f"[brain] provayderlar soni {n} (10 kutilgan)")
        # trading analysis button
        page.goto(f"{a.url}/#trading/analysis")
        page.click("#go")
        try:
            page.wait_for_selector("#out .stat", timeout=30000)
        except Exception as e:
            problems.append(f"[trading] tahlil chiqmadi: {e}")
        browser.close()
    print("\n=== MUAMMOLAR:", len(problems))
    for pr in problems:
        print(" ", pr[:400])
    print("USER", a.user)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
