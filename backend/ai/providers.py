"""AI provider connectors: Anthropic Claude, OpenAI ChatGPT, Google Gemini.

Unified interface:
    await provider.chat(system, messages, tools=None, max_tokens, temperature) -> AIResponse
Messages use a neutral format:
    {"role": "user"|"assistant", "content": str | list[block]}
    blocks: {"type":"text","text"} | {"type":"image","media_type","data"(b64)}
            | {"type":"tool_use","id","name","input"} | {"type":"tool_result","tool_use_id","content","is_error"}
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field

import httpx

log = logging.getLogger("robin.providers")

TIMEOUT = httpx.Timeout(180.0, connect=15.0)


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict
    signature: str = ""   # Gemini 3 thought signature (must be sent back with the call)


@dataclass
class AIResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    provider: str = ""
    model: str = ""
    stop_reason: str = ""
    usage: dict = field(default_factory=dict)


class ProviderError(Exception):
    pass


def _blocks(content) -> list[dict]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return content


# ---------------------------------------------------------------- Anthropic
class AnthropicProvider:
    name = "anthropic"
    url = "https://api.anthropic.com/v1/messages"

    def __init__(self, api_key: str, model: str):
        self.api_key, self.model = api_key, model

    def _convert(self, messages):
        out = []
        for m in messages:
            blocks = []
            for b in _blocks(m["content"]):
                t = b["type"]
                if t == "text":
                    blocks.append({"type": "text", "text": b["text"] or " "})
                elif t == "image":
                    blocks.append({"type": "image", "source": {"type": "base64", "media_type": b["media_type"],
                                                               "data": b["data"]}})
                elif t == "tool_use":
                    blocks.append({"type": "tool_use", "id": b["id"], "name": b["name"], "input": b["input"]})
                elif t == "tool_result":
                    blocks.append({"type": "tool_result", "tool_use_id": b["tool_use_id"],
                                   "content": str(b["content"]), "is_error": bool(b.get("is_error"))})
            out.append({"role": m["role"], "content": blocks})
        return out

    async def chat(self, system, messages, tools=None, max_tokens=4096, temperature=0.4, model=None):
        body = {"model": model or self.model, "max_tokens": max_tokens, "system": system,
                "messages": self._convert(messages)}
        if temperature is not None:
            body["temperature"] = temperature
        if tools:
            body["tools"] = [{"name": t["name"], "description": t["description"],
                              "input_schema": t["parameters"]} for t in tools]
        headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.post(self.url, headers=headers, json=body)
            if r.status_code == 400 and "temperature" in r.text:
                body.pop("temperature", None)
                r = await c.post(self.url, headers=headers, json=body)
        if r.status_code >= 400:
            raise ProviderError(f"Anthropic {r.status_code}: {r.text[:500]}")
        data = r.json()
        resp = AIResponse(provider=self.name, model=body["model"], stop_reason=data.get("stop_reason", ""),
                          usage=data.get("usage", {}))
        for b in data.get("content", []):
            if b["type"] == "text":
                resp.text += b["text"]
            elif b["type"] == "tool_use":
                resp.tool_calls.append(ToolCall(b["id"], b["name"], b.get("input") or {}))
        return resp


# ---------------------------------------------------------------- OpenAI-compatible (OpenAI, Groq, OpenRouter, ...)
# Every provider below speaks the OpenAI /chat/completions dialect. Model names change often, so each one has a
# preferred chain, and when a model is missing ROBIN discovers available ones via GET /models.
CATALOG: dict[str, dict] = {
    "openai": {"title": "ChatGPT (OpenAI)", "base": "https://api.openai.com/v1", "models": ["gpt-4o", "gpt-4o-mini"],
               "key_url": "https://platform.openai.com/api-keys", "max_tools": 128, "free": False,
               "prefer": [r"^gpt-5(\.\d)?$", r"^gpt-4\.1$", r"^gpt-4o$", r"mini"]},
    "groq": {"title": "Groq", "base": "https://api.groq.com/openai/v1",
             "models": ["llama-3.3-70b-versatile", "openai/gpt-oss-120b", "qwen/qwen3-32b", "llama-3.1-8b-instant"],
             "key_url": "https://console.groq.com/keys", "max_tools": 16, "free": True,
             "prefer": [r"gpt-oss-120b", r"llama-?4", r"llama-3\.3-70b", r"qwen", r"70b", r"instant"]},
    "openrouter": {"title": "OpenRouter (:free modellar)", "base": "https://openrouter.ai/api/v1",
                   "models": ["openrouter/free"], "key_url": "https://openrouter.ai/keys", "max_tools": 32,
                   "free": True, "free_only": True,
                   "headers": {"HTTP-Referer": "http://127.0.0.1:8000", "X-Title": "ROBIN AI"},
                   "prefer": [r"deepseek.*:free", r"qwen.*:free", r"llama.*70b.*:free", r"gemma.*:free", r":free$"]},
    "mistral": {"title": "Mistral (Experiment)", "base": "https://api.mistral.ai/v1",
                "models": ["mistral-large-latest", "mistral-medium-latest", "mistral-small-latest"],
                "key_url": "https://console.mistral.ai/api-keys", "max_tools": 40, "free": True, "short_ids": True,
                "prefer": [r"mistral-large-latest", r"mistral-medium-latest", r"mistral-small-latest"]},
    "cerebras": {"title": "Cerebras", "base": "https://api.cerebras.ai/v1",
                 "models": ["gpt-oss-120b", "llama-3.3-70b", "qwen-3-32b", "llama3.1-8b"],
                 "key_url": "https://cloud.cerebras.ai/platform", "max_tools": 16, "free": True,
                 "prefer": [r"gpt-oss-120b", r"llama-?4", r"llama-3\.3-70b", r"qwen", r"8b"]},
    "github": {"title": "GitHub Models", "base": "https://models.github.ai/inference",
               "models": ["openai/gpt-4.1", "openai/gpt-4o", "openai/gpt-4.1-mini", "meta/Llama-3.3-70B-Instruct"],
               "key_url": "https://github.com/settings/tokens", "max_tools": 24, "free": True,
               "models_url": "https://models.github.ai/catalog/models",
               "headers": {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
               "prefer": [r"openai/gpt-5", r"openai/gpt-4\.1$", r"openai/gpt-4o$", r"mini", r"llama"]},
    "cloudflare": {"title": "Cloudflare Workers AI", "base": "https://api.cloudflare.com/client/v4/accounts/{account}/ai/v1",
                   "models": ["@cf/meta/llama-3.3-70b-instruct-fp8-fast", "@cf/meta/llama-4-scout-17b-16e-instruct",
                              "@cf/qwen/qwen2.5-coder-32b-instruct"],
                   "key_url": "https://dash.cloudflare.com/profile/api-tokens", "max_tools": 12, "free": True,
                   "key_format": "ACCOUNT_ID:API_TOKEN", "no_discovery": True, "prefer": []},
    "huggingface": {"title": "Hugging Face", "base": "https://router.huggingface.co/v1",
                    "models": ["openai/gpt-oss-120b", "meta-llama/Llama-3.3-70B-Instruct", "Qwen/Qwen2.5-72B-Instruct"],
                    "key_url": "https://huggingface.co/settings/tokens", "max_tools": 16, "free": True,
                    "prefer": [r"gpt-oss-120b", r"llama-3\.3-70b", r"qwen.*72b", r"instruct"]},
}


def _short_id(i: str) -> str:
    """Mistral requires 9-char alphanumeric tool-call ids."""
    import hashlib
    return hashlib.md5(i.encode()).hexdigest()[:9]


def valid_model_name(model: str | None) -> str:
    """Users sometimes type the provider name ("Gemini", "Groq") into the model field. Real model ids always
    contain '-', '/', '.', ':', '@' or a digit → anything else is ignored (= automatic model)."""
    m = (model or "").strip()
    return m if re.search(r"[-/.:@\d]", m) else ""


REASONING = re.compile(r"gpt-oss|qwen-?3|deepseek-r|magistral|reason|thinking|^o\d", re.I)


class OpenAICompatProvider:
    cooldown: dict[str, float] = {}       # "provider:model" → until
    discovered: dict[str, list] = {}      # provider → model ids from /models
    accounts: dict[str, str] = {}         # Cloudflare token hash → account id

    def __init__(self, name: str, api_key: str, model: str | None = None):
        self.name = name
        self.cfg = CATALOG[name]
        base = self.cfg["base"]
        api_key = api_key.strip()
        if "{account}" in base and ":" in api_key:  # Cloudflare: key is "ACCOUNT_ID:TOKEN"
            account, _, api_key = api_key.partition(":")
            base = base.replace("{account}", account.strip())
        # (token only → account id is looked up on first use, see _resolve_account)
        self.base, self.api_key = base.rstrip("/"), api_key.strip()
        model = valid_model_name(model)
        self.model = model or self.cfg["models"][0]
        self._configured = self.model
        self.max_tools = self.cfg.get("max_tools", 64)

    # -- message conversion ------------------------------------------------
    def _convert(self, system, messages, images: bool = True):
        sid = _short_id if self.cfg.get("short_ids") else (lambda x: x)
        out = [{"role": "system", "content": system}]
        for m in messages:
            blocks = _blocks(m["content"])
            if m["role"] == "assistant":
                text = "".join(b.get("text", "") for b in blocks if b["type"] == "text")
                calls = [{"id": sid(b["id"]), "type": "function",
                          "function": {"name": b["name"], "arguments": json.dumps(b["input"], ensure_ascii=False)}}
                         for b in blocks if b["type"] == "tool_use"]
                msg = {"role": "assistant", "content": text or ("" if calls else " ")}
                if calls:
                    msg["tool_calls"] = calls
                out.append(msg)
                continue
            parts, has_image = [], False
            for b in blocks:
                if b["type"] == "tool_result":
                    out.append({"role": "tool", "tool_call_id": sid(b["tool_use_id"]), "content": str(b["content"])})
                elif b["type"] == "text":
                    parts.append({"type": "text", "text": b["text"]})
                elif b["type"] == "image":
                    if images:
                        has_image = True
                        parts.append({"type": "image_url",
                                      "image_url": {"url": f"data:{b['media_type']};base64,{b['data']}"}})
                    else:
                        parts.append({"type": "text", "text": "[rasm: bu model rasmni ko'ra olmaydi]"})
            if parts:
                # plain string content is the most widely supported form when there is no image
                content = parts if has_image else "\n".join(p["text"] for p in parts)
                out.append({"role": "user", "content": content})
        return out

    # -- model discovery ------------------------------------------------------
    async def _discover(self, c: httpx.AsyncClient) -> list[str]:
        if self.cfg.get("no_discovery"):
            return []
        if self.name in self.discovered:
            return self.discovered[self.name]
        ids: list[str] = []
        try:
            url = self.cfg.get("models_url") or f"{self.base}/models"
            r = await c.get(url, headers=self._headers(), timeout=20)
            data = r.json()
            items = data.get("data", data) if isinstance(data, dict) else data
            for it in items or []:
                mid = it.get("id") if isinstance(it, dict) else str(it)
                if not mid:
                    continue
                if self.cfg.get("free_only") and not mid.endswith(":free"):
                    continue
                params = it.get("supported_parameters") if isinstance(it, dict) else None
                if params is not None and "tools" not in params:
                    continue
                if any(x in mid.lower() for x in ("embed", "whisper", "tts", "guard", "moderation", "image", "vision-only")):
                    continue
                ids.append(mid)
        except Exception:
            ids = []
        ranked = []
        for pat in self.cfg.get("prefer", []):
            ranked += [m for m in ids if re.search(pat, m, re.I) and m not in ranked]
        ranked += [m for m in ids if m not in ranked]
        self.discovered[self.name] = ranked[:12]
        return self.discovered[self.name]

    def _headers(self) -> dict:
        h = {"Authorization": f"Bearer {self.api_key}"}
        h.update(self.cfg.get("headers", {}))
        return h

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=30) as c:
            self.discovered.pop(self.name, None)
            return await self._discover(c)

    # -- chat ---------------------------------------------------------------
    MISSING = ("not found", "does not exist", "invalid model", "decommission", "not available", "unknown model",
               "no endpoints", "deprecated", "no longer", "not a valid model", "model name format")

    async def _resolve_account(self, c: httpx.AsyncClient) -> None:
        """Cloudflare token without ACCOUNT_ID → ask the API which account the token belongs to."""
        if "{account}" not in self.base:
            return
        key = hashlib.md5(self.api_key.encode()).hexdigest()
        acc = self.accounts.get(key)
        if not acc:
            try:
                r = await c.get("https://api.cloudflare.com/client/v4/accounts", headers=self._headers(), timeout=20)
                res = (r.json() or {}).get("result") or []
                acc = res[0]["id"] if res else ""
            except Exception:
                acc = ""
            if not acc:
                raise ProviderError("Cloudflare Workers AI: Account ID topilmadi. Kalitni ACCOUNT_ID:API_TOKEN "
                                    "ko'rinishida kiriting (Account ID — Cloudflare dashboard'ning o'ng ustunida) "
                                    "yoki tokenga 'Account Settings: Read' ruxsatini bering.")
            self.accounts[key] = acc
        self.base = self.base.replace("{account}", acc)

    async def chat(self, system, messages, tools=None, max_tokens=4096, temperature=0.4, model=None):
        """Walk the model chain: busy / out-of-quota / retired models are parked and the next one is tried."""
        first = valid_model_name(model) or self.model
        chain = [first] + [m for m in self.cfg["models"] if m != first]
        errors: list[str] = []
        discovered_once = False
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            await self._resolve_account(c)
            i = 0
            while i < len(chain):
                mdl = chain[i]
                i += 1
                ck = f"{self.name}:{mdl}"
                if self.cooldown.get(ck, 0) > time.time() and i < len(chain):
                    continue
                status, payload = await self._call(c, mdl, system, messages, tools, max_tokens, temperature)
                if status == 200:
                    try:
                        return self._parse(payload, mdl)
                    except ProviderError as e:      # empty answer → try the next model instead of failing
                        status, payload = 502, str(e)
                errors.append(f"{mdl}: {status} {str(payload)[:180]}")
                low = str(payload).lower()
                if status in (401, 403) and "model" not in low:
                    break                                   # bad key — other models won't help
                missing = status == 404 or ("model" in low and any(w in low for w in self.MISSING))
                retriable = status in (0, 408, 413, 429, 500, 502, 503, 504, 529) or "too large" in low
                if not (missing or retriable):
                    break
                self.cooldown[ck] = time.time() + (86400 if missing else 120 if status in (0, 429) else 60)
                if not discovered_once:
                    discovered_once = True
                    chain += [m for m in await self._discover(c) if m not in chain]
        raise ProviderError(f"{self.cfg['title']} " + " | ".join(errors[-4:]))

    async def _call(self, c, mdl, system, messages, tools, max_tokens, temperature) -> tuple[int, object]:
        """One model; degrades gracefully when the model can't take images or tools."""
        use_tools, use_images = bool(tools), True
        for _ in range(3):
            body = {"model": mdl, "messages": self._convert(system, messages, use_images),
                    "max_tokens": max_tokens, "temperature": temperature}
            if REASONING.search(mdl):
                # reasoning models spend tokens "thinking" first — short calls would come back empty
                body["max_tokens"] = min(max_tokens + 2048, 32768)
                if self.name in ("groq", "cerebras", "openrouter", "huggingface") and "gpt-oss" in mdl:
                    body["reasoning_effort"] = "low"
            if use_tools:
                body["tools"] = [{"type": "function", "function": t} for t in tools]
            try:
                r = await c.post(f"{self.base}/chat/completions", headers=self._headers(), json=body)
            except httpx.TimeoutException:
                return 0, "timeout"
            except httpx.HTTPError as e:
                return 0, f"{type(e).__name__}: {e}"
            if r.status_code < 400:
                try:
                    data = r.json()
                except ValueError:
                    return 502, f"JSON bo'lmagan javob: {r.text[:120]!r} (tarmoq yoki mintaqa cheklovi bo'lishi mumkin)"
                if isinstance(data, dict) and data.get("choices"):
                    return 200, data
                return 502, f"kutilmagan javob: {str(data)[:160]}"
            low = r.text.lower()
            if r.status_code in (400, 422) and use_images and "image" in low:
                use_images = False
                continue
            if r.status_code in (400, 422) and use_tools and ("tool" in low or "function" in low):
                use_tools = False          # model can't call tools → still answer in text
                continue
            return r.status_code, _err_msg(r)
        return 400, "so'rov qabul qilinmadi"

    def _parse(self, data: dict, mdl: str) -> AIResponse:
        ch = (data.get("choices") or [{}])[0]
        msg = ch.get("message") or {}
        text = msg.get("content") or ""
        if isinstance(text, list):
            text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()   # reasoning models (qwen, deepseek)
        resp = AIResponse(text=text, provider=self.name, model=data.get("model") or mdl,
                          stop_reason=ch.get("finish_reason", ""), usage=data.get("usage", {}))
        for n, tc in enumerate(msg.get("tool_calls") or []):
            fn = tc.get("function") or {}
            raw = fn.get("arguments") or "{}"
            if isinstance(raw, dict):
                args = raw
            else:
                try:
                    args = json.loads(raw)
                except json.JSONDecodeError:
                    args = {}
            resp.tool_calls.append(ToolCall(tc.get("id") or f"call_{n}_{fn.get('name')}", fn.get("name", ""), args))
        if not resp.text and not resp.tool_calls:
            raise ProviderError(f"{self.cfg['title']}: bo'sh javob ({mdl})")
        return resp


def _err_msg(r: httpx.Response) -> str:
    try:
        j = r.json()
        e = j.get("error", j)
        if isinstance(e, dict):
            return str(e.get("message") or e)
        if isinstance(e, list) and e:
            return str(e[0].get("message", e[0]) if isinstance(e[0], dict) else e[0])
        return str(e)
    except ValueError:
        return r.text


class OpenAIProvider(OpenAICompatProvider):
    def __init__(self, api_key: str, model: str):
        super().__init__("openai", api_key, model)


# ---------------------------------------------------------------- Gemini
def _gemini_schema(schema: dict) -> dict:
    """Gemini accepts an OpenAPI subset — strip unsupported keys.
    Gemini rejects OBJECT schemas with empty `properties`, so free-form objects are sent as JSON strings
    (executor.coerce_args turns them back into dicts)."""
    if not isinstance(schema, dict):
        return schema
    if schema.get("type") == "object" and not schema.get("properties"):
        return {"type": "string", "description": (schema.get("description", "") + " (JSON obyekt matni)").strip()}
    out = {}
    for k, v in schema.items():
        if k in ("additionalProperties", "default", "$schema", "examples"):
            continue
        if k == "properties":
            out[k] = {pk: _gemini_schema(pv) for pk, pv in v.items()}
        elif k == "items":
            out[k] = _gemini_schema(v)
        else:
            out[k] = v
    return out


def _gemini_function(t: dict) -> dict:
    fn = {"name": t["name"], "description": t["description"]}
    if (t.get("parameters") or {}).get("properties"):  # parameterless tools must omit `parameters`
        fn["parameters"] = _gemini_schema(t["parameters"])
    return fn


class GeminiProvider:
    """Gemini with a model fallback chain. Quotas (429) and overload (503) are per model, so when one model is
    busy or out of quota ROBIN moves to the next one and parks the busy model for a while (cooldown)."""
    name = "gemini"
    resolved: dict[str, str] = {}      # configured name → working model (self-healing when Google retires a model)
    cooldown: dict[str, float] = {}    # model → unix time until which it is skipped
    FALLBACK = ["gemini-3.5-flash", "gemini-flash-latest", "gemini-3.8-flash", "gemini-3.5-flash-lite",
                "gemini-flash-lite-latest", "gemini-3.1-flash-lite"]

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = self.resolved.get(model, model)
        self._configured = model

    def _candidates(self, first: str) -> list[str]:
        now = time.time()
        chain = [first] + [m for m in self.FALLBACK if m != first]
        ready = [m for m in chain if self.cooldown.get(m, 0) <= now]
        return ready or chain  # everything parked → try anyway

    async def _pick_model(self) -> str | None:
        """Model was retired (404): choose the best available flash model from the live model list."""
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.get("https://generativelanguage.googleapis.com/v1beta/models",
                                params={"pageSize": 200}, headers={"x-goog-api-key": self.api_key})
            names = [m["name"].split("/", 1)[1] for m in r.json().get("models", [])
                     if "generateContent" in m.get("supportedGenerationMethods", [])]
        except Exception:
            return None
        if "gemini-flash-latest" in names:
            return "gemini-flash-latest"

        def version(n: str) -> float:
            m = re.match(r"gemini-(\d+(?:\.\d+)?)-flash$", n)
            return float(m.group(1)) if m else -1.0
        best = max(names, key=version, default=None)
        return best if best and version(best) > 0 else None

    def _convert(self, messages):
        contents, names = [], {}
        for m in messages:
            parts = []
            for b in _blocks(m["content"]):
                if b["type"] == "text":
                    parts.append({"text": b["text"] or " "})
                elif b["type"] == "image":
                    parts.append({"inline_data": {"mime_type": b["media_type"], "data": b["data"]}})
                elif b["type"] == "tool_use":
                    names[b["id"]] = b["name"]
                    part = {"functionCall": {"name": b["name"], "args": b["input"]}}
                    if b.get("signature"):  # Gemini 3 requires the thought signature to be echoed back
                        part["thoughtSignature"] = b["signature"]
                    parts.append(part)
                elif b["type"] == "tool_result":
                    parts.append({"functionResponse": {"name": names.get(b["tool_use_id"], "tool"),
                                                       "response": {"result": str(b["content"])}}})
            contents.append({"role": "model" if m["role"] == "assistant" else "user", "parts": parts})
        return contents

    async def chat(self, system, messages, tools=None, max_tokens=4096, temperature=0.4, model=None):
        # Gemini 3 "thinks" before answering and the thinking counts against maxOutputTokens → add headroom,
        # otherwise short calls (router, JSON) come back empty.
        body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": self._convert(messages),
                "generationConfig": {"maxOutputTokens": min(max_tokens + 3000, 65536), "temperature": temperature}}
        if tools:
            body["tools"] = [{"functionDeclarations": [_gemini_function(t) for t in tools]}]
        base = "https://generativelanguage.googleapis.com/v1beta/models/"
        errors: list[str] = []
        r = None
        mdl = model or self.model
        async with httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=15.0)) as c:
            for mdl in self._candidates(mdl):
                try:
                    r = await c.post(f"{base}{mdl}:generateContent", headers={"x-goog-api-key": self.api_key}, json=body)
                except httpx.TimeoutException:
                    self.cooldown[mdl] = time.time() + 120
                    errors.append(f"{mdl}: timeout")
                    continue
                if r.status_code < 400:
                    break
                code = r.status_code
                try:
                    msg = r.json().get("error", {}).get("message", r.text)
                except ValueError:
                    msg = r.text
                errors.append(f"{mdl}: {code} {msg[:160]}")
                if code == 404:
                    self.cooldown[mdl] = time.time() + 86400        # retired model
                elif code in (429, 500, 503, 504):
                    self.cooldown[mdl] = time.time() + (180 if code == 429 else 60)
                else:
                    break                                            # 400/401/403: other models won't help
            else:
                r = None
        if r is None or r.status_code >= 400:
            if errors and all(" 404 " in e for e in errors) and not model:
                new = await self._pick_model()   # every known model retired → discover a new one
                if new:
                    self.FALLBACK.insert(0, new)
            raise ProviderError("Gemini " + " | ".join(errors[-4:]))
        if not model and mdl != self.model:
            log.info("Gemini: %s band/kvota — %s ishlatildi", self.model, mdl)
        data = r.json()
        resp = AIResponse(provider=self.name, model=mdl, usage=data.get("usageMetadata", {}))
        cands = data.get("candidates") or []
        if not cands:
            raise ProviderError(f"Gemini bo'sh javob: {str(data)[:300]}")
        resp.stop_reason = cands[0].get("finishReason", "")
        for i, p in enumerate(cands[0].get("content", {}).get("parts", [])):
            if p.get("thought"):
                continue  # internal reasoning summary, not part of the answer
            if "functionCall" in p:
                fc = p["functionCall"]
                resp.tool_calls.append(ToolCall(f"gem_{i}_{fc['name']}", fc["name"], fc.get("args") or {},
                                                p.get("thoughtSignature", "")))
            elif "text" in p:
                resp.text += p["text"]
        if not resp.text and not resp.tool_calls:
            raise ProviderError(f"Gemini bo'sh javob (finishReason={resp.stop_reason})")
        return resp


async def embed(text: str, keys: dict) -> list[float]:
    """Semantic embedding via OpenAI or Gemini; empty list if unavailable (local fallback is used)."""
    text = text[:8000]
    try:
        if keys.get("openai"):
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.post("https://api.openai.com/v1/embeddings",
                                 headers={"Authorization": f"Bearer {keys['openai']}"},
                                 json={"model": "text-embedding-3-small", "input": text})
            if r.status_code == 200:
                return r.json()["data"][0]["embedding"]
        if keys.get("gemini"):
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.post("https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent",
                                 headers={"x-goog-api-key": keys["gemini"]},
                                 json={"content": {"parts": [{"text": text}]}})
            if r.status_code == 200:
                return r.json()["embedding"]["values"]
    except httpx.HTTPError:
        pass
    return []
