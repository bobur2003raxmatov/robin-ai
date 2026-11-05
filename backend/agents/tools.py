"""All ROBIN tools (function-calling). Computer tools run locally or on the user's connected device."""
from __future__ import annotations

import asyncio
import html
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx
from sqlalchemy import desc, select

from backend.agents import computer
from backend.agents.devices import bridge
from backend.agents.events import hub
from backend.agents.registry import TOOLS, S, ToolContext, tool
from backend.config import settings
from backend.memory.database import Command, Reminder, SessionLocal, TradeJournal
from backend.memory.settings_store import DEFAULTS, get_setting, set_setting
from backend.security.permissions import wrap_untrusted


async def run_computer(ctx: ToolContext, fn: str, **args):
    """Route a computer primitive to the connected desktop agent, or run locally."""
    if bridge.pick(ctx.user_id, ctx.device_id):
        return await bridge.call(ctx.user_id, fn, args, ctx.device_id)
    if settings.LOCAL_EXECUTION:
        return await asyncio.to_thread(computer.FUNCS[fn], **args)
    raise RuntimeError("Kompyuter ulanmagan: desktop/robin_agent.py ni noutbukda ishga tushiring")


def _ctool(name: str, description: str, props: dict, required: list, risk: str, module: str):
    async def f(ctx: ToolContext, **args):
        return await run_computer(ctx, name, **args)
    tool(name, description, props, required, risk=risk, module=module, computer=True)(f)


# ============================================================ COMPUTER TOOLS
_ctool("list_dir", "Papka ichidagi fayl va papkalarni ko'rsatadi.",
       {"path": S("Papka yo'li, masalan ~/Desktop"), "pattern": S("glob, masalan *.xlsx")}, ["path"], "safe", "files_read")
_ctool("read_file", "Faylni o'qiydi (txt, kod, pdf, docx, xlsx, csv).", {"path": S("Fayl yo'li")}, ["path"], "safe", "files_read")
_ctool("write_file", "Faylga matn yozadi (eski versiya zaxiralanadi).",
       {"path": S("Fayl yo'li"), "content": S("Matn"), "append": S("Oxiriga qo'shish", "boolean")},
       ["path", "content"], "medium", "files_write")
_ctool("search_files", "Kompyuterdan fayllarni nomi (yoki matni) bo'yicha qidiradi.",
       {"query": S("Qidiruv so'zi"), "directory": S("Qayerdan (standart ~)"),
        "extensions": S("masalan: xlsx,csv"), "content": S("Fayl ichidan ham qidirish", "boolean")},
       ["query"], "safe", "files_read")
_ctool("move_path", "Fayl/papkani ko'chiradi yoki nomini o'zgartiradi.", {"src": S("Manba"), "dst": S("Manzil")},
       ["src", "dst"], "medium", "files_write")
_ctool("delete_path", "Fayl/papkani o'chiradi (ROBIN savatiga ko'chiriladi, tiklash mumkin).", {"path": S("Yo'l")},
       ["path"], "high", "files_delete")
_ctool("organize_folder", "Papkadagi fayllarni turiga yoki oyiga qarab saralaydi.",
       {"directory": S("Papka"), "by": S("type | month")}, ["directory"], "medium", "files_write")
_ctool("open_path", "Fayl yoki papkani standart dasturda ochadi.", {"path": S("Yo'l")}, ["path"], "low", "apps")
_ctool("create_document", "Hujjat yaratadi: .docx, .xlsx (JSON {sheet:[[header..],[row..]]}), .md, .txt, .csv.",
       {"path": S("Yangi fayl yo'li"), "content": S("Mazmun"), "title": S("Sarlavha")}, ["path", "content"],
       "medium", "files_write")
_ctool("open_app", "Dasturni ochadi (chrome, excel, word, telegram, vscode, kalkulyator, ...).",
       {"name": S("Dastur nomi"), "args": S("Argumentlar")}, ["name"], "low", "apps")
_ctool("close_app", "Dasturni yopadi.", {"name": S("Dastur nomi")}, ["name"], "medium", "apps")
_ctool("list_windows", "Ochiq oynalar ro'yxati.", {}, [], "safe", "apps")
_ctool("focus_window", "Sarlavhasi bo'yicha oynani oldinga chiqaradi.", {"title": S("Oyna sarlavhasi qismi")},
       ["title"], "low", "apps")
_ctool("mouse_click", "Ekrandagi nuqtani bosadi (oxirgi screenshot koordinatalarida).",
       {"x": S("x", "number"), "y": S("y", "number"), "button": S("left|right|middle"),
        "clicks": S("1 yoki 2", "integer")}, ["x", "y"], "low", "mouse_keyboard")
_ctool("mouse_move", "Sichqonchani siljitadi.", {"x": S("x", "number"), "y": S("y", "number")}, ["x", "y"],
       "low", "mouse_keyboard")
_ctool("drag", "Sudrab olib borish.", {"x1": S("", "number"), "y1": S("", "number"), "x2": S("", "number"),
                                       "y2": S("", "number")}, ["x1", "y1", "x2", "y2"], "low", "mouse_keyboard")
_ctool("type_text", "Matn yozadi (o'zbek/rus unicode qo'llab-quvvatlanadi).",
       {"text": S("Matn"), "enter": S("Oxirida Enter", "boolean")}, ["text"], "low", "mouse_keyboard")
_ctool("hotkey", "Klaviatura kombinatsiyasi: ctrl+s, alt+tab, win+d, ctrl+shift+esc.", {"keys": S("Tugmalar")},
       ["keys"], "low", "mouse_keyboard")
_ctool("press_key", "Bitta tugmani bosadi (enter, esc, tab, down, f5...).",
       {"key": S("Tugma"), "times": S("Necha marta", "integer")}, ["key"], "low", "mouse_keyboard")
_ctool("scroll", "Aylantiradi (manfiy = pastga).", {"amount": S("miqdor", "integer")}, [], "safe", "mouse_keyboard")
_ctool("wait", "Kutadi (soniya).", {"seconds": S("soniya", "number")}, ["seconds"], "safe", "")
_ctool("screenshot", "Ekran rasmini oladi va SENGA ko'rsatadi (Computer Vision).", {}, [], "low", "screen_vision")
_ctool("clipboard_get", "Bufer matnini o'qiydi.", {}, [], "low", "mouse_keyboard")
_ctool("clipboard_set", "Buferga matn yozadi.", {"text": S("Matn")}, ["text"], "low", "mouse_keyboard")
_ctool("open_url", "Brauzerda sahifa ochadi.", {"url": S("URL")}, ["url"], "low", "web")
_ctool("media_control", "Media: play_pause|next|prev|volume_up|volume_down|mute.", {"action": S("amal")},
       ["action"], "safe", "apps")
_ctool("run_shell", "Terminal buyrug'ini bajaradi (PowerShell/bash). Faqat zarur bo'lganda.",
       {"command": S("Buyruq"), "cwd": S("Ishchi papka"), "timeout": S("soniya", "integer")}, ["command"],
       "high", "shell")
_ctool("run_python", "Python kodini izolyatsiyalangan sandbox muhitida bajaradi (hisob-kitob, tahlil, grafik).",
       {"code": S("Python kodi"), "workdir": S("Ishchi papka (ixtiyoriy)")}, ["code"], "medium", "python")
_ctool("system_resources", "CPU, RAM, disk, internet, batareya holati.", {}, [], "safe", "")
_ctool("excel_analyze", "Excel/CSV faylni to'liq tahlil qiladi: statistika, guruh jami, XATOLAR (bo'sh, dublikat, "
       "manfiy, outlier, miqdor×narx≠jami, formula xatolari).", {"path": S("Fayl"), "sheet": S("Varaq (ixtiyoriy)")},
       ["path"], "safe", "files_read")
_ctool("excel_query", "Excel ma'lumotlari ustida operatsiya: head|describe|groupby_sum|groupby_mean|groupby_count|"
       "sort|value_counts|pivot|filter.", {"path": S("Fayl"), "operation": S("operatsiya"), "sheet": S(""),
                                           "column": S("Ustun"), "by": S("Guruhlash ustuni (pivot: 'qator,ustun')"),
                                           "filter_expr": S("pandas query, masalan: Summa > 1000")},
       ["path", "operation"], "safe", "files_read")
_ctool("excel_report", "Excel hisobot yaratadi: xulosa, guruhlar + diagramma, xatolar varag'i.",
       {"path": S("Manba fayl"), "output": S("Natija .xlsx yo'li"), "title": S("Sarlavha"),
        "group_by": S("Guruhlash ustuni"), "value": S("Qiymat ustuni"), "notes": S("Izoh/xulosa")},
       ["path", "output"], "medium", "files_write")
_ctool("excel_write_cells", "Excel kataklariga qiymat/formula yozadi, masalan {\"D2\":\"=B2*C2\"}.",
       {"path": S("Fayl"), "sheet": S("Varaq"), "cells": S("{katak: qiymat}", "object")},
       ["path", "sheet", "cells"], "medium", "files_write")


@tool("system_security_scan", "Kompyuterda shubhali jarayonlar, ochiq portlar, tashqi ulanishlar va avtoyuklanishni "
      "tekshiradi (Security Monitor, faqat himoya).", {}, [], risk="safe", computer=True)
async def _sec(ctx: ToolContext):
    return await run_computer(ctx, "security_scan")


# ============================================================ VISION
async def _vision(ctx: ToolContext, question: str) -> tuple[str, dict]:
    shot = await run_computer(ctx, "screenshot")
    r = await ctx.brain.complete(
        "Sen ekran tasvirini tahlil qiluvchi Computer Vision modulisan. Aniq va qisqa javob ber.",
        [{"role": "user", "content": [{"type": "image", "media_type": shot["media_type"], "data": shot["image_b64"]},
                                      {"type": "text", "text": question}]}], max_tokens=1200, temperature=0.1)
    return r.text, shot


@tool("screen_read", "Ekranni ko'rib savolga javob beradi: qaysi oyna ochiq, tugmalar, matnlar, xatolar, jadval.",
      {"question": S("Ekran haqida savol")}, ["question"], risk="low", module="screen_vision", computer=True)
async def screen_read(ctx: ToolContext, question: str):
    text, shot = await _vision(ctx, question)
    return {"answer": text, "active_window": shot.get("active_window")}


@tool("click_text", "Ekrandagi element (tugma, havola, matn)ni tavsifi bo'yicha topib bosadi.",
      {"target": S("Masalan: 'Save tugmasi', 'Kirish', 'Fayl menyusi'"), "double": S("Ikki marta", "boolean")},
      ["target"], risk="low", module="mouse_keyboard", computer=True)
async def click_text(ctx: ToolContext, target: str, double: bool = False):
    from backend.ai.brain import parse_json
    text, _shot = await _vision(ctx, f"'{target}' elementining markaz koordinatasini rasm piksellarida top. "
                                     "Faqat JSON: {\"found\": true/false, \"x\": int, \"y\": int, \"what\": \"...\"}")
    data = parse_json(text)
    if not data.get("found"):
        return {"ok": False, "error": f"'{target}' ekranda topilmadi", "vision": text[:300]}
    res = await run_computer(ctx, "mouse_click", x=data["x"], y=data["y"], clicks=2 if double else 1)
    return {"ok": True, "clicked": data, **res}


# ============================================================ WEB
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}


def html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript|svg|head).*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</h\d>|</li>|</tr>", "\n", raw)
    txt = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    txt = re.sub(r"[ \t\r\f\v]+", " ", txt)
    return re.sub(r"\n\s*\n+", "\n\n", txt).strip()


def _bing_url(href: str) -> str:
    """Bing wraps results as bing.com/ck/a?...&u=a1<base64url(target)> — unwrap to the real address."""
    href = html.unescape(href)
    if "bing.com/ck/a" in href:
        u = parse_qs(urlparse(href).query).get("u", [""])[0]
        if u.startswith("a1"):
            import base64
            try:
                return base64.urlsafe_b64decode(u[2:] + "=" * (-len(u[2:]) % 4)).decode()
            except Exception:
                pass
    return href


async def _search_bing(c: httpx.AsyncClient, query: str, n: int) -> list[dict]:
    r = await c.get("https://www.bing.com/search", params={"q": query, "count": max(n, 10)})
    out = []
    for chunk in r.text.split('<li class="b_algo"')[1:]:
        a = re.search(r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', chunk, re.S)
        if not a:
            continue
        sn = re.search(r'<p[^>]*>(.*?)</p>', chunk, re.S)
        out.append({"title": html_to_text(a.group(2)), "url": _bing_url(a.group(1)),
                    "snippet": html_to_text(sn.group(1)) if sn else ""})
        if len(out) >= n:
            break
    return out


async def _search_ddg(c: httpx.AsyncClient, query: str, n: int) -> list[dict]:
    r = await c.post("https://html.duckduckgo.com/html/", data={"q": query})
    out = []
    for m in re.finditer(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?'
                         r'(?:<a[^>]+class="result__snippet"[^>]*>(.*?)</a>)?', r.text, re.S):
        href = html.unescape(m.group(1))
        if "uddg=" in href:
            href = unquote(parse_qs(urlparse(href).query).get("uddg", [href])[0])
        out.append({"title": html_to_text(m.group(2)), "url": href, "snippet": html_to_text(m.group(3) or "")})
        if len(out) >= n:
            break
    return out


@tool("web_search", "Internetdan qidiradi (natijalar: sarlavha, havola, qisqa matn).",
      {"query": S("Qidiruv so'rovi"), "max_results": S("Natijalar soni", "integer")}, ["query"], risk="safe", module="web")
async def web_search(ctx: ToolContext, query: str, max_results: int = 8):
    """Several engines in turn (DuckDuckGo often answers bots with a captcha)."""
    results: list[dict] = []
    async with httpx.AsyncClient(timeout=20, headers=UA, follow_redirects=True) as c:
        for engine in (_search_bing, _search_ddg):
            try:
                results = await engine(c, query, max_results)
            except httpx.HTTPError:
                results = []
            if results:
                break
    body = "\n".join(f"{i + 1}. {x['title']}\n   {x['url']}\n   {x['snippet']}" for i, x in enumerate(results))
    return wrap_untrusted(f"web_search:{query}", body or "natija yo'q (qidiruv tizimlari javob bermadi — "
                                                         "boshqa so'z bilan bir marta urin yoki web_fetch ishlat)")


@tool("web_fetch", "Veb-sahifa matnini o'qiydi.", {"url": S("URL"), "max_chars": S("", "integer")}, ["url"],
      risk="safe", module="web")
async def web_fetch(ctx: ToolContext, url: str, max_chars: int = 15000):
    async with httpx.AsyncClient(timeout=30, headers=UA, follow_redirects=True) as c:
        r = await c.get(url)
    ct = r.headers.get("content-type", "")
    text = html_to_text(r.text) if "html" in ct else r.text
    return wrap_untrusted(url, text, max_chars)


# ============================================================ MEMORY & KNOWLEDGE
@tool("remember", "Muhim ma'lumotni uzoq muddatli xotiraga saqlaydi.",
      {"content": S("Ma'lumot"), "kind": S("fact|preference|project|decision|workflow"), "subject": S("Mavzu/loyiha"),
       "importance": S("0..1", "number")}, ["content"], risk="safe")
async def remember(ctx: ToolContext, content: str, kind: str = "fact", subject: str = "", importance: float = 0.6):
    mid = await ctx.memory.remember(content, kind, subject, importance)
    return {"saved": mid}


@tool("recall", "Xotiradan qidiradi (oldingi suhbatlar, afzalliklar, loyihalar).", {"query": S("Nima haqida")},
      ["query"], risk="safe")
async def recall(ctx: ToolContext, query: str):
    items = await ctx.memory.search(query, limit=10)
    return [{"kind": m.kind, "subject": m.subject, "content": m.content, "date": m.created_at.strftime("%Y-%m-%d")}
            for m in items] or "Xotirada topilmadi"


@tool("project_context", "Loyiha bo'yicha barcha ma'lumot: maqsad, texnologiya, bajarilgan va qolgan ishlar.",
      {"name": S("Loyiha nomi")}, ["name"], risk="safe")
async def project_context(ctx: ToolContext, name: str):
    return await ctx.memory.project_context(name)


@tool("knowledge_search", "Yuklangan hujjatlar bilimlar bazasidan (Knowledge Center) semantik qidiradi.",
      {"query": S("Savol")}, ["query"], risk="safe")
async def knowledge_search(ctx: ToolContext, query: str):
    res = await ctx.memory.search_knowledge(query, limit=6)
    return wrap_untrusted("knowledge_base", "\n\n".join(f"[{r['doc']} #{r['idx']} score={r['score']}]\n{r['text']}"
                                                         for r in res) or "topilmadi")


# ============================================================ NOTES
@tool("write_note", "Notes bo'limiga eslatma/qayd yozadi (foydalanuvchi 'yozib qo'y', 'notesga saqla' desa yoki muhim "
      "natija, reja, yo'riqnoma, uchrashuv xulosasini saqlash kerak bo'lsa). Markdown qo'llab-quvvatlanadi.",
      {"title": S("Sarlavha"), "body": S("Matn (markdown)"), "pinned": S("Yuqoriga mahkamlash", "boolean")},
      ["title", "body"], risk="safe")
async def write_note(ctx: ToolContext, title: str, body: str, pinned: bool = False):
    from backend.memory.notes import add_note
    nid = await add_note(ctx.user_id, title, body, "robin", auto=True, pinned=pinned)
    return {"saved": bool(nid), "id": nid}


@tool("search_notes", "Notes bo'limidan (yo'riqnomalar, avtomatik yozuvlar, foydalanuvchi qaydlari) qidiradi.",
      {"query": S("Qidiruv so'zi")}, ["query"], risk="safe")
async def search_notes(ctx: ToolContext, query: str):
    from backend.memory.database import Note
    from backend.memory.notes import system_notes
    q = query.lower()
    async with SessionLocal() as db:
        rows = (await db.scalars(select(Note).where(Note.user_id == ctx.user_id,
                                                    Note.title.ilike(f"%{query}%") | Note.body.ilike(f"%{query}%"))
                                 .order_by(desc(Note.created_at)).limit(10))).all()
    found = [{"title": n.title, "date": n.created_at.strftime("%Y-%m-%d"), "text": n.body[:1500]} for n in rows]
    for s in system_notes():
        if q in s["body"].lower() or q in s["title"].lower():
            i = s["body"].lower().find(q)
            found.append({"title": s["title"], "date": "yo'riqnoma", "text": s["body"][max(0, i - 600): i + 1200]})
    return found or "Notes'da topilmadi"


# ============================================================ DAILY MANAGER / REMINDERS
def _parse_when(when: str) -> datetime:
    dt = datetime.fromisoformat(when.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.astimezone()  # local time
    return dt.astimezone(timezone.utc)


@tool("create_reminder", "Eslatma yoki uchrashuv belgilaydi. 'Ertaga 10:00' kabi vaqtni ISO formatga o'zing aylantir "
      "(hozirgi sanaga nisbatan, mahalliy vaqt).",
      {"title": S("Nomi"), "when": S("ISO vaqt, masalan 2026-11-06T10:00"), "note": S("Izoh"),
       "kind": S("reminder|meeting|task"), "repeat": S("''|daily|weekly")}, ["title", "when"], risk="low")
async def create_reminder(ctx: ToolContext, title: str, when: str, note: str = "", kind: str = "reminder",
                          repeat: str = ""):
    due = _parse_when(when)
    async with SessionLocal() as db:
        r = Reminder(user_id=ctx.user_id, title=title, note=note, kind=kind, due_at=due, repeat=repeat)
        db.add(r)
        await db.commit()
    await hub.emit(ctx.user_id, "reminders_changed", {})
    return {"created": r.id, "title": title, "due_local": due.astimezone().strftime("%Y-%m-%d %H:%M"), "kind": kind}


@tool("list_reminders", "Kelgusi eslatma va uchrashuvlar.", {"days": S("Necha kun oldinga", "integer")}, [], risk="safe")
async def list_reminders(ctx: ToolContext, days: int = 7):
    end = datetime.now(timezone.utc) + timedelta(days=days)
    async with SessionLocal() as db:
        rows = (await db.scalars(select(Reminder).where(Reminder.user_id == ctx.user_id, Reminder.done.is_(False),
                                                        Reminder.due_at <= end).order_by(Reminder.due_at))).all()
    return [{"id": r.id, "title": r.title, "kind": r.kind, "when": r.due_at.astimezone().strftime("%Y-%m-%d %H:%M"),
             "note": r.note} for r in rows] or "Rejalashtirilgan narsa yo'q"


@tool("cancel_reminder", "Eslatmani bekor qiladi.", {"id": S("Eslatma ID")}, ["id"], risk="low")
async def cancel_reminder(ctx: ToolContext, id: str):
    async with SessionLocal() as db:
        r = await db.get(Reminder, id)
        if not r or r.user_id != ctx.user_id:
            return {"ok": False}
        r.done = True
        await db.commit()
    return {"ok": True}


@tool("export_calendar", "Eslatma/uchrashuvlarni .ics faylga eksport qiladi (Google/Outlook kalendarga import uchun).",
      {"path": S("Fayl yo'li .ics")}, ["path"], risk="low", module="files_write")
async def export_calendar(ctx: ToolContext, path: str):
    async with SessionLocal() as db:
        rows = (await db.scalars(select(Reminder).where(Reminder.user_id == ctx.user_id, Reminder.done.is_(False)))).all()
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//ROBIN//UZ"]
    for r in rows:
        st = r.due_at.astimezone(timezone.utc)
        lines += ["BEGIN:VEVENT", f"UID:{r.id}@robin", f"DTSTART:{st:%Y%m%dT%H%M%SZ}",
                  f"DTEND:{(st + timedelta(minutes=30)):%Y%m%dT%H%M%SZ}", f"SUMMARY:{r.title}",
                  f"DESCRIPTION:{r.note}", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return await run_computer(ctx, "write_file", path=path, content="\r\n".join(lines))


# ============================================================ COMMUNICATION
@tool("notify_owner", "Egaga (adminga) xabar/ogohlantirish yuboradi: dashboard + Telegram.",
      {"title": S("Sarlavha"), "body": S("Matn"), "level": S("info|warning|error|success")}, ["title"], risk="safe")
async def notify_owner(ctx: ToolContext, title: str, body: str = "", level: str = "info"):
    await hub.notify(ctx.user_id, title, body, level)
    return {"sent": True}


@tool("send_telegram", "Ulangan Telegram chatga (egaga) xabar yuboradi.", {"text": S("Xabar")}, ["text"],
      risk="low", module="email_messages")
async def send_telegram(ctx: ToolContext, text: str):
    from backend.integrations.telegram_bot import send_to_user
    ok = await send_to_user(ctx.user_id, text)
    return {"sent": ok}


# ============================================================ SELF-CONFIG / COMMANDS / AGENTS
@tool("update_robin_settings", "ROBIN o'z sozlamalarini o'zgartiradi (admin fikri asosida): personality, brain, voice, "
      "avatar, trading, notifications.", {"key": S("Bo'lim"), "value": S("O'zgartiriladigan qiymatlar", "object"),
                                          "reason": S("Nima uchun")}, ["key", "value"], risk="medium",
      module="self_config")
async def update_robin_settings(ctx: ToolContext, key: str, value: dict, reason: str = ""):
    if key not in DEFAULTS or key == "permissions":
        return {"ok": False, "error": "Bu bo'limni ROBIN o'zgartira olmaydi"}
    new = await set_setting(ctx.user_id, key, value)
    await hub.emit(ctx.user_id, "settings_changed", {"key": key})
    return {"ok": True, "key": key, "now": new}


@tool("list_commands", "Saqlangan foydalanuvchi buyruqlari ro'yxati.", {}, [], risk="safe")
async def list_commands(ctx: ToolContext):
    async with SessionLocal() as db:
        rows = (await db.scalars(select(Command).where(Command.user_id == ctx.user_id))).all()
    return [{"name": c.name, "triggers": c.triggers, "description": c.description, "steps": len(c.steps)} for c in rows]


@tool("run_saved_command", "Saqlangan buyruqni nomi bo'yicha bajaradi.", {"name": S("Buyruq nomi")}, ["name"], risk="low")
async def run_saved_command(ctx: ToolContext, name: str):
    from backend.agents.executor import run_command_by_name
    return await run_command_by_name(ctx, name)


@tool("delegate", "Vazifani ixtisoslashgan agentga topshiradi (Multi-Agent): developer, analyst, researcher, "
      "translator, designer, manager, security, trader.", {"agent": S("Agent"), "task": S("Aniq topshiriq")},
      ["agent", "task"], risk="safe")
async def delegate(ctx: ToolContext, agent: str, task: str):
    from backend.agents.executor import run_agent
    res = await run_agent(ctx, task, agent=agent, history=[], depth=1)
    return res["text"]


@tool("create_background_task", "Autopilot navbatiga mustaqil vazifa qo'shadi (fon rejimida bajariladi).",
      {"title": S("Sarlavha"), "goal": S("To'liq maqsad")}, ["title", "goal"], risk="low")
async def create_background_task(ctx: ToolContext, title: str, goal: str):
    from backend.agents.executor import autopilot
    t = await autopilot.submit(ctx.user_id, title, goal, background=True)
    return {"task_id": t.id, "status": "queued"}


# ============================================================ SMART HOME
@tool("smart_home", "Aqlli uy (Home Assistant): qurilmani yoqish/o'chirish, holatni bilish.",
      {"action": S("turn_on|turn_off|toggle|state|list"), "entity_id": S("masalan light.mehmonxona")},
      ["action"], risk="medium", module="smart_home")
async def smart_home(ctx: ToolContext, action: str, entity_id: str = ""):
    cfg = await get_setting(ctx.user_id, "smart_home")
    keys = await get_setting(ctx.user_id, "api_keys")
    url, token = cfg.get("home_assistant_url"), keys.get("home_assistant")
    if not url or not token:
        return {"ok": False, "error": "Home Assistant URL va token sozlanmagan (Settings → Smart Home)"}
    h = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=15) as c:
        if action == "list":
            r = await c.get(f"{url}/api/states", headers=h)
            return [{"entity_id": s["entity_id"], "state": s["state"]} for s in r.json()][:150]
        if action == "state":
            r = await c.get(f"{url}/api/states/{entity_id}", headers=h)
            return r.json()
        domain = entity_id.split(".")[0]
        r = await c.post(f"{url}/api/services/{domain}/{action}", headers=h, json={"entity_id": entity_id})
        return {"ok": r.status_code < 300, "status": r.status_code}


# ============================================================ TRADING EXPERT
TRADER = ("trader",)


@tool("market_analyze", "Bozorni to'liq texnik tahlil qiladi: trend, S/R, RSI, MACD, EMA, Bollinger, ATR, Fibonacci, "
      "price action, Smart Money (BOS/CHoCH/OB/FVG/likvidlik). Har qanday bozor: BTCUSDT, EURUSD, AAPL, GOLD, SPX.",
      {"symbol": S("Simvol"), "interval": S("1m|5m|15m|1h|4h|1d|1w"), "multi_timeframe": S("Bir nechta TF", "boolean")},
      ["symbol"], risk="safe", module="trading_paper", agents=TRADER)
async def market_analyze(ctx: ToolContext, symbol: str, interval: str = "1h", multi_timeframe: bool = False):
    from backend.trading import indicators, market
    if multi_timeframe:
        out = {}
        for tf in ("15m", "1h", "4h", "1d"):
            try:
                a = indicators.full_analysis(await market.candles(symbol, tf, 400))
                out[tf] = {"price": a["price"], "trend": a["trend"], "rsi": a["indicators"]["rsi14"],
                           "structure": a["smart_money"]["structure"], "levels": a["levels"]}
            except Exception as e:
                out[tf] = {"error": str(e)}
        return out
    df = await market.candles(symbol, interval, 500)
    return indicators.full_analysis(df)


@tool("risk_calculate", "Risk Manager: pozitsiya hajmi, SL/TP (ATR asosida ham), R:R, limitlarni tekshirish.",
      {"symbol": S("Simvol"), "side": S("buy|sell"), "entry": S("Kirish narxi", "number"),
       "stop_loss": S("SL (bo'lmasa ATR bilan hisoblanadi)", "number"), "take_profit": S("TP", "number"),
       "balance": S("Hisob balansi (bo'lmasa demo balans)", "number"), "risk_pct": S("Risk %", "number"),
       "rr": S("Kerakli R:R", "number")}, ["symbol", "side"], risk="safe", module="trading_paper", agents=TRADER)
async def risk_calculate(ctx: ToolContext, symbol: str, side: str, entry: float | None = None,
                         stop_loss: float | None = None, take_profit: float | None = None, balance: float | None = None,
                         risk_pct: float | None = None, rr: float = 2.0):
    from backend.trading import broker, indicators, market, risk
    df = await market.candles(symbol, "1h", 200)
    entry = entry or float(df["close"].iloc[-1])
    a = float(indicators.atr(df).iloc[-1])
    if stop_loss is None:
        st = risk.sl_tp_from_atr(entry, a, side, rr=rr)
        stop_loss, take_profit = st["stop_loss"], take_profit or st["take_profit"]
    if take_profit is None:
        dist = abs(entry - stop_loss) * rr
        take_profit = entry + dist if side == "buy" else entry - dist
    lim = await broker.limits(ctx.user_id)
    bal = balance or (await broker.account(ctx.user_id)).balance
    rp = risk_pct or lim["max_risk_per_trade_pct"]
    size = risk.position_size(bal, rp, entry, stop_loss)
    plan = {"symbol": symbol, "side": side, "entry": entry, "stop_loss": stop_loss, "take_profit": take_profit,
            "qty": size["qty"]}
    chk = await broker.check_plan(ctx.user_id, plan)
    return {"plan": chk["plan"], "position": size, "atr": a, "rr": risk.risk_reward(entry, stop_loss, take_profit),
            "balance": bal, "risk_pct": rp, "warnings": chk["warnings"], "blocks": chk["blocks"]}


@tool("backtest", "Strategiyani tarixiy ma'lumotda sinaydi yoki barcha strategiyalarni bellashtiradi "
      "(strategy='competition'). Strategiyalar: ema_cross, rsi_reversion, macd, bollinger_breakout, trend_pullback.",
      {"symbol": S("Simvol"), "strategy": S("Strategiya yoki competition"), "interval": S("TF"),
       "bars": S("Shamlar soni", "integer"), "params": S("Parametrlar", "object")}, ["symbol"], risk="safe",
      module="trading_paper", agents=TRADER)
async def backtest_tool(ctx: ToolContext, symbol: str, strategy: str = "competition", interval: str = "1h",
                        bars: int = 1000, params: dict | None = None):
    from backend.trading import backtest, market
    df = await market.candles(symbol, interval, bars)
    if strategy == "competition":
        return backtest.competition(df)
    res = backtest.backtest(df, strategy, params=params)
    res.pop("equity_curve", None)
    return res


@tool("paper_trade", "Demo hisobda (virtual pul, real narx) savdo ochadi/yopadi. Trading Simulator.",
      {"action": S("open|close|status"), "symbol": S("Simvol"), "side": S("buy|sell"), "qty": S("Miqdor", "number"),
       "stop_loss": S("SL", "number"), "take_profit": S("TP", "number"), "trade_id": S("Yopish uchun ID"),
       "strategy": S("Strategiya nomi"), "reason": S("Savdo sababi")}, ["action"], risk="low",
      module="trading_paper", agents=TRADER)
async def paper_trade(ctx: ToolContext, action: str, symbol: str = "", side: str = "buy", qty: float = 0,
                      stop_loss: float | None = None, take_profit: float | None = None, trade_id: str = "",
                      strategy: str = "", reason: str = ""):
    from backend.trading import broker, market
    if action == "status":
        acc = await broker.account(ctx.user_id)
        async with SessionLocal() as db:
            rows = (await db.scalars(select(TradeJournal).where(TradeJournal.user_id == ctx.user_id,
                                                               TradeJournal.status == "open"))).all()
        return {"balance": acc.balance, "start_balance": acc.start_balance,
                "open": [{"id": t.id, "symbol": t.symbol, "side": t.side, "qty": t.qty, "entry": t.entry,
                          "sl": t.stop_loss, "tp": t.take_profit} for t in rows]}
    if action == "close":
        return await broker.close_trade(ctx.user_id, trade_id)
    entry = await market.price(symbol)
    return await broker.paper_open(ctx.user_id, {"symbol": symbol, "side": side, "qty": qty, "entry": entry,
                                                 "stop_loss": stop_loss, "take_profit": take_profit,
                                                 "strategy": strategy, "reason": reason})


@tool("live_trade", "REAL hisobda broker orqali savdo. Har doim egasining tasdig'i so'raladi (Approval Center).",
      {"symbol": S("Simvol"), "side": S("buy|sell"), "qty": S("Miqdor", "number"), "entry": S("Taxminiy narx", "number"),
       "stop_loss": S("SL (majburiy)", "number"), "take_profit": S("TP", "number"), "strategy": S(""),
       "reason": S("Tahlil xulosasi")}, ["symbol", "side", "qty", "stop_loss"], risk="critical",
      module="trading_live", agents=TRADER)
async def live_trade(ctx: ToolContext, **plan):
    from backend.trading import broker
    return await broker.live_order(ctx.user_id, plan)


@tool("trading_journal", "Savdolar jurnali va statistika (win-rate, PnL), AI Mentor tahlili uchun.",
      {"limit": S("Nechta", "integer")}, [], risk="safe", module="trading_paper", agents=TRADER)
async def trading_journal(ctx: ToolContext, limit: int = 30):
    async with SessionLocal() as db:
        rows = (await db.scalars(select(TradeJournal).where(TradeJournal.user_id == ctx.user_id)
                                 .order_by(desc(TradeJournal.opened_at)).limit(limit))).all()
    closed = [t for t in rows if t.status == "closed"]
    wins = [t for t in closed if t.pnl > 0]
    return {"stats": {"trades": len(closed), "win_rate_pct": round(len(wins) / len(closed) * 100, 1) if closed else 0,
                      "total_pnl": round(sum(t.pnl for t in closed), 2)},
            "trades": [{"id": t.id, "mode": t.mode, "symbol": t.symbol, "side": t.side, "qty": t.qty, "entry": t.entry,
                        "exit": t.exit, "sl": t.stop_loss, "tp": t.take_profit, "pnl": t.pnl, "status": t.status,
                        "strategy": t.strategy, "reason": t.reason, "emotion": t.emotion,
                        "date": t.opened_at.strftime("%Y-%m-%d %H:%M")} for t in rows]}


def all_tool_names() -> list[str]:
    return sorted(TOOLS)
