"""ROBIN Multi-Brain: combines Claude, ChatGPT and Gemini with automatic fallback,
specialist routing, optional ensemble answers and self-review."""
from __future__ import annotations

import asyncio
import json
import logging
import re

from backend.ai import prompts
import time
from collections import deque

from backend.ai.providers import (CATALOG, AIResponse, AnthropicProvider, GeminiProvider, OpenAICompatProvider,
                                  ProviderError, valid_model_name)
from backend.config import settings
from backend.memory.settings_store import get_setting

log = logging.getLogger("robin.brain")

ALL_PROVIDERS = ["anthropic", "openai", "gemini", "groq", "openrouter", "mistral", "cerebras", "github",
                 "cloudflare", "huggingface"]
PROVIDER_META = {
    "anthropic": {"title": "Claude (Anthropic)", "key_url": "https://console.anthropic.com/settings/keys", "free": False},
    "gemini": {"title": "Google Gemini (AI Studio)", "key_url": "https://aistudio.google.com/apikey", "free": True},
    **{n: {"title": c["title"], "key_url": c["key_url"], "free": c["free"], "key_format": c.get("key_format", "")}
       for n, c in CATALOG.items()},
}

# ---------------------------------------------------------------- live provider health (for Settings → Holat)
_HEALTH: dict[str, deque] = {}


def record_health(name: str, ok: bool, seconds: float, error: str = "") -> None:
    _HEALTH.setdefault(name, deque(maxlen=200)).append((time.time(), ok, round(seconds, 2), error[:200]))


def provider_health(name: str) -> dict:
    h = list(_HEALTH.get(name, ()))
    if not h:
        return {"calls": 0, "success_pct": None, "avg_seconds": None, "last_error": ""}
    ok = [x for x in h if x[1]]
    return {"calls": len(h), "success_pct": round(len(ok) / len(h) * 100, 1),
            "avg_seconds": round(sum(x[2] for x in ok) / len(ok), 2) if ok else None,
            "last_error": next((x[3] for x in reversed(h) if not x[1]), ""), "last_ok": h[-1][1]}


ALWAYS_TOOLS = {"remember", "recall", "notify_owner", "create_reminder", "system_resources", "web_search",
                "read_file", "list_dir", "open_app", "screenshot"}


def prune_tools(tools: list | None, messages: list, limit: int) -> list | None:
    """Keep at most `limit` tools: ones already used in this conversation, core tools, then the ones whose
    name/description best match the latest user request."""
    if not tools or len(tools) <= limit:
        return tools
    used = set()
    last_user = ""
    for m in messages:
        c = m["content"]
        if isinstance(c, list):
            for b in c:
                if b.get("type") == "tool_use":
                    used.add(b["name"])
                elif b.get("type") == "text" and m["role"] == "user":
                    last_user = b["text"]
        elif m["role"] == "user":
            last_user = c
    words = set(re.findall(r"[a-zа-яёʻ']{3,}", last_user.lower()))

    def score(t):
        hay = (t["name"].replace("_", " ") + " " + t["description"]).lower()
        s = sum(1 for w in words if w[:5] in hay)
        return (t["name"] in used) * 100 + (t["name"] in ALWAYS_TOOLS) * 10 + s
    return sorted(tools, key=score, reverse=True)[:limit]


class NoProviderError(Exception):
    pass


def parse_json(text: str) -> dict:
    """Robustly extract the first JSON object from model output."""
    if not text:
        return {}
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidate = m.group(1) if m else None
    if candidate is None:
        start = text.find("{")
        if start == -1:
            return {}
        depth, end = 0, -1
        in_str = esc = False
        for i, ch in enumerate(text[start:], start):
            if in_str:
                esc = (ch == "\\") and not esc
                if ch == '"' and not esc:
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        candidate = text[start:end + 1] if end != -1 else text[start:]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        try:
            return json.loads(re.sub(r",\s*([}\]])", r"\1", candidate))
        except json.JSONDecodeError:
            return {}


class Brain:
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.providers: dict = {}
        self.order: list[str] = []
        self.cfg: dict = {}
        self.keys: dict = {}

    async def load(self) -> "Brain":
        self.cfg = await get_setting(self.user_id, "brain")
        user_keys = await get_setting(self.user_id, "api_keys")
        self.keys = {n: (user_keys.get(n) or getattr(settings, f"{n.upper()}_API_KEY", "") or "").strip()
                     for n in ALL_PROVIDERS}
        for name in ALL_PROVIDERS:
            key = self.keys[name]
            if not key:
                continue
            model = valid_model_name(self.cfg.get(f"{name}_model"))   # "Gemini" typed as a model → automatic
            if name == "anthropic":
                self.providers[name] = AnthropicProvider(key, model or settings.ANTHROPIC_MODEL)
            elif name == "gemini":
                self.providers[name] = GeminiProvider(key, model or settings.GEMINI_MODEL)
            else:
                self.providers[name] = OpenAICompatProvider(name, key, model or getattr(settings, f"{name.upper()}_MODEL", "") or None)
        order = list(self.cfg.get("providers") or [])
        primary = settings.PRIMARY_PROVIDER
        if primary in order:
            order.remove(primary)
            order.insert(0, primary)
        self.order = [p for p in order if p in self.providers] + \
                     [p for p in ALL_PROVIDERS if p in self.providers and p not in order]
        return self

    @property
    def available(self) -> bool:
        return bool(self.providers)

    def status(self) -> dict:
        out = {}
        for n in ALL_PROVIDERS:
            meta = PROVIDER_META[n]
            p = self.providers.get(n)
            out[n] = {"connected": p is not None, "model": getattr(p, "model", None), "title": meta["title"],
                      "key_url": meta["key_url"], "free": meta["free"], "key_format": meta.get("key_format", ""),
                      "health": provider_health(n)}
        return {"providers": out, "order": self.order}

    async def complete(self, system: str, messages: list, tools: list | None = None,
                       prefer: str | None = None, max_tokens: int | None = None,
                       temperature: float | None = None, fast: bool = False) -> AIResponse:
        if not self.providers:
            raise NoProviderError("AI kaliti sozlanmagan. Dashboard → Brain bo'limida Claude, ChatGPT yoki "
                                  "Gemini API kalitini kiriting (yoki .env faylida).")
        order = list(self.order)
        if prefer and prefer in order:
            order.remove(prefer)
            order.insert(0, prefer)
        errors = []
        for name in order:
            prov = self.providers[name]
            model = None
            if fast:
                model = {"anthropic": settings.ANTHROPIC_FAST_MODEL, "gemini": settings.GEMINI_FAST_MODEL}.get(name)
            # Providers with small free-tier token limits get only the tools relevant to this request.
            p_tools = prune_tools(tools, messages, getattr(prov, "max_tools", 999)) if tools else None
            t0 = time.time()
            try:
                # Gemini and OpenAI-compatible providers already walk their own model chains on 429/503.
                resp = await prov.chat(system, messages, tools=p_tools,
                                       max_tokens=max_tokens or int(self.cfg.get("max_tokens", 4096)),
                                       temperature=self.cfg.get("temperature", 0.4) if temperature is None else temperature,
                                       model=model)
                record_health(name, True, time.time() - t0)
                return resp
            except ProviderError as e:
                errors.append(f"{name}: {str(e)[:300]}")
            except Exception as e:  # network etc.
                errors.append(f"{name}: {type(e).__name__}: {e}")
            record_health(name, False, time.time() - t0, errors[-1])
            log.warning("Provider %s failed, falling back: %s", name, errors[-1][:200])
        raise ProviderError("Barcha AI provayderlar xato qaytardi:\n" + "\n".join(errors))

    async def ask_json(self, system: str, user_text: str, fast: bool = True, max_tokens: int = 1500) -> dict:
        r = await self.complete(system, [{"role": "user", "content": user_text}], fast=fast,
                                max_tokens=max_tokens, temperature=0.1)
        return parse_json(r.text)

    async def route(self, text: str) -> dict:
        """Pick the specialist. Keyword routing is free and handles most messages; the AI router (one extra
        call) is used only for longer requests where intent/complexity is ambiguous — this saves API quota."""
        agent = guess_agent(text)
        heuristic = {"agent": agent, "complex": looks_complex(text), "language": guess_language(text),
                     "emotion": "neutral", "title": text[:60]}
        if len(text) < 140 or (agent != "assistant" and not heuristic["complex"]):
            return heuristic
        try:
            data = await self.ask_json(prompts.ROUTER_PROMPT, text[:3000], max_tokens=200)
        except Exception:
            return heuristic
        if data.get("agent") not in prompts.SPECIALISTS:
            data["agent"] = agent
        return {**heuristic, **data}

    async def review(self, task: str, result: str) -> dict:
        try:
            # Prefer a *different* provider than the primary for an independent second opinion.
            other = self.order[1] if len(self.order) > 1 else None
            r = await self.complete(prompts.REVIEW_PROMPT,
                                    [{"role": "user", "content": f"VAZIFA:\n{task[:4000]}\n\nNATIJA:\n{result[:12000]}"}],
                                    prefer=other, max_tokens=800, temperature=0.1)
            return parse_json(r.text) or {"ok": True, "score": 7, "issues": []}
        except Exception as e:
            return {"ok": True, "score": None, "issues": [f"review o'tkazilmadi: {e}"]}

    async def ensemble(self, system: str, messages: list) -> AIResponse:
        """Ask every connected AI, then let the primary merge the best answer."""
        names = list(self.providers)
        if len(names) < 2:
            return await self.complete(system, messages)
        results = await asyncio.gather(*[self.providers[n].chat(system, messages, max_tokens=2000)
                                         for n in names], return_exceptions=True)
        drafts = [f"[{n}]\n{r.text}" for n, r in zip(names, results) if isinstance(r, AIResponse) and r.text]
        if len(drafts) < 2:
            return await self.complete(system, messages)
        merge_msgs = messages + [{"role": "assistant", "content": "Bir nechta qoralama tayyorladim."},
                                 {"role": "user", "content": "Quyidagi qoralamalardan eng to'g'ri va to'liq yakuniy "
                                  "javobni tuz (qoralamalarni eslatma):\n\n" + "\n\n".join(drafts)}]
        return await self.complete(system, merge_msgs)


KEYWORDS = {
    "trader": ["trade", "trading", "savdo strateg", "forex", "crypto", "kripto", "bitcoin", "btc", "eth", "rsi",
               "macd", "stop loss", "take profit", "birja", "aksiya", "stock", "signal", "treyd", "трейд", "биткоин"],
    "analyst": ["excel", "xlsx", "csv", "jadval", "hisobot", "tahlil", "diagramma", "formula", "отчет", "таблиц"],
    "developer": ["kod", "code", "python", "javascript", "bug", "xato kod", "dastur", "funksiya", "api", "код"],
    "researcher": ["internetdan", "izla", "qidir", "research", "raqobatchi", "найди", "поиск"],
    "translator": ["tarjima", "translate", "перевод", "переведи"],
    "manager": ["uchrashuv", "eslat", "reja", "kalendar", "meeting", "remind", "напомни", "встреч"],
    "security": ["virus", "xavfsizlik", "shubhali", "security", "malware", "безопасн"],
    "designer": ["dizayn", "design", "logo", "rang", "interfeys"],
}


STEP_MARKERS = re.compile(r"\b(keyin|so'ng|so‘ng|undan keyin|then|after that|потом|затем|после этого)\b|\n\s*\d+[.)]",
                          re.IGNORECASE)


def looks_complex(text: str) -> bool:
    """Multi-step autonomous job (→ Autopilot) vs a single request."""
    return len(text) > 160 and len(STEP_MARKERS.findall(text)) >= 2


def guess_language(text: str) -> str:
    cyr = sum(1 for ch in text if "Ѐ" <= ch <= "ӿ")
    if cyr > len(text) * 0.3:
        return "uz" if any(ch in "ўқғҳЎҚҒҲ" for ch in text) else "ru"
    return "uz" if re.search(r"[og]['ʻ’]|\b(va|uchun|bilan|qil|men|sen)\b", text.lower()) else "en"


def guess_agent(text: str) -> str:
    t = text.lower()
    scores = {a: sum(k in t for k in kws) for a, kws in KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] else "assistant"


async def get_brain(user_id: str) -> Brain:
    return await Brain(user_id).load()
