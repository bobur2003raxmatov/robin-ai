"""Agent loop tests with a scripted fake AI: tool calling, approval gate, autopilot plan execution."""
import asyncio

import pytest

from backend.agents import executor
from backend.agents.registry import ToolContext
from backend.ai.providers import AIResponse, ToolCall
from backend.memory.database import User, SessionLocal, init_db
from backend.memory.memory import Memory


class FakeBrain:
    keys = {}
    available = True
    order = ["fake"]

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    async def complete(self, system, messages, tools=None, **kw):
        self.calls.append(messages)
        return self.script.pop(0) if self.script else AIResponse(text="tayyor", provider="fake")

    async def ensemble(self, system, messages):
        return await self.complete(system, messages)


async def _user(name):
    await init_db()
    async with SessionLocal() as db:
        u = User(username=name, password_hash="x")
        db.add(u)
        await db.commit()
        return u.id


def test_tool_call_loop(tmp_path):
    async def go():
        uid = await _user("agent_loop")
        f = tmp_path / "note.txt"
        f.write_text("ROBIN test fayli")
        brain = FakeBrain([AIResponse(tool_calls=[ToolCall("t1", "read_file", {"path": str(f)})], provider="fake"),
                           AIResponse(text="Faylda: ROBIN test fayli", provider="fake")])
        ctx = ToolContext(user_id=uid, brain=brain, memory=Memory(uid))
        res = await executor.run_agent(ctx, "note.txt ni o'qi")
        assert res["text"] == "Faylda: ROBIN test fayli"
        assert res["steps"][0]["tool"] == "read_file"
        # the tool result was fed back to the model
        last_user = brain.calls[1][-1]["content"]
        assert last_user[0]["type"] == "tool_result" and "ROBIN test fayli" in last_user[0]["content"]
    asyncio.run(go())


def test_high_risk_waits_for_approval_and_rejection_is_respected():
    async def go():
        uid = await _user("approval_user")
        brain = FakeBrain([AIResponse(tool_calls=[ToolCall("t1", "run_shell", {"command": "echo hi"})], provider="fake"),
                           AIResponse(text="Rad etildi, to'xtadim", provider="fake")])
        ctx = ToolContext(user_id=uid, brain=brain, memory=Memory(uid))
        task = asyncio.create_task(executor.run_agent(ctx, "echo qil"))
        for _ in range(100):
            await asyncio.sleep(0.02)
            if executor.approvals.waiters:
                break
        assert executor.approvals.waiters, "approval was not requested"
        aid = next(iter(executor.approvals.waiters))
        assert await executor.approvals.decide(uid, aid, False)
        res = await task
        assert res["text"].startswith("Rad etildi")
        fed_back = brain.calls[1][-1]["content"][0]["content"]
        assert "RAD ETDI" in fed_back
    asyncio.run(go())


def test_coerce_args():
    from backend.agents.registry import TOOLS
    a = executor.coerce_args(TOOLS["excel_write_cells"].parameters,
                             {"path": "x.xlsx", "sheet": "S", "cells": '{"A1": "=1+1"}', "junk": 1})
    assert a == {"path": "x.xlsx", "sheet": "S", "cells": {"A1": "=1+1"}}
    b = executor.coerce_args(TOOLS["press_key"].parameters, {"key": "enter", "times": "3"})
    assert b["times"] == 3


def test_gemini_schema_has_no_empty_objects():
    from backend.agents.registry import TOOLS
    from backend.ai.providers import _gemini_function

    def walk(s):
        if isinstance(s, dict):
            if s.get("type") == "object":
                assert s.get("properties"), s
            for v in s.values():
                walk(v)
    for t in TOOLS.values():
        fn = _gemini_function(t.schema())
        walk(fn.get("parameters", {}))


def test_text_only_flattens_tool_blocks():
    msgs = [{"role": "user", "content": "salom"},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "1", "name": "wait", "input": {"seconds": 1}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "1", "content": "ok"}]},
            {"role": "user", "content": "davom"}]
    flat = executor._text_only(msgs)
    assert [m["role"] for m in flat] == ["user", "assistant", "user"]
    assert all(isinstance(m["content"], str) for m in flat)


def test_unknown_tool_reported():
    async def go():
        uid = await _user("unknown_tool")
        ctx = ToolContext(user_id=uid, brain=None, memory=Memory(uid))
        out, _ = await executor.execute_tool(ctx, "no_such_tool", {})
        assert out.startswith("XATO")
    asyncio.run(go())


def test_openai_compat_conversion_and_catalog():
    from backend.ai.providers import CATALOG, OpenAICompatProvider
    assert {"groq", "openrouter", "mistral", "cerebras", "github", "cloudflare", "huggingface"} <= set(CATALOG)
    cf = OpenAICompatProvider("cloudflare", "ACC42:tok")
    assert "/accounts/ACC42/ai/v1" in cf.base and cf.api_key == "tok"
    mi = OpenAICompatProvider("mistral", "k")
    msgs = [{"role": "user", "content": "salom"},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "toolu_ABCDEFG123", "name": "wait", "input": {}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_ABCDEFG123", "content": "ok"}]}]
    out = mi._convert("sys", msgs)
    call_id = out[2]["tool_calls"][0]["id"]
    assert len(call_id) == 9 and out[3]["tool_call_id"] == call_id     # Mistral 9-char ids, consistent
    assert out[1]["content"] == "salom"                                # plain string when no image


def test_prune_tools_keeps_relevant_and_used():
    from backend.agents.registry import TOOLS
    from backend.ai.brain import prune_tools
    tools = [t.schema() for t in TOOLS.values()]
    msgs = [{"role": "assistant", "content": [{"type": "tool_use", "id": "1", "name": "backtest", "input": {}}]},
            {"role": "user", "content": "Excel faylni tahlil qil va hisobot yarat"}]
    kept = {t["name"] for t in prune_tools(tools, msgs, 16)}
    assert len(kept) == 16 and "backtest" in kept and "excel_analyze" in kept


def test_provider_error_messages():
    m = executor.provider_error_message
    assert "kvota" in m("Gemini gemini-3.5-flash: 429 quota exceeded")
    assert "band" in m("x: 503 high demand")
    assert "kalit" in m("Groq llama: 401 Invalid API Key")
