"""🤖 Claude menu (icon gate, admin-only, stream parser), Mijoz paneli, /claude chat command, deploy webhook."""
import hashlib
import hmac

import pytest
from fastapi.testclient import TestClient

from backend.integrations.claude_code import ClaudeBridge, bridge
from backend.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _reg(c, name):
    r = c.post("/api/auth/register", json={"username": name, "password": "secret123", "full_name": name.title()})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}, r.json()["user"]


def _make_admin(client, uid):
    from backend.memory.database import SessionLocal, User

    async def go():
        async with SessionLocal() as db:
            u = await db.get(User, uid)
            u.is_admin = True
            await db.commit()
        from backend.security import services
        services._cache.clear()
    client.portal.call(go)


def test_claude_gate_and_admin_only(client, monkeypatch):
    ha, a = _reg(client, "cladmin")
    _make_admin(client, a["id"])
    hu, _ = _reg(client, "cluser")
    assert client.get("/api/claude/status", headers=hu).status_code == 403
    st = client.post("/api/claude/toggle", json={"enabled": False}, headers=ha).json()
    assert st["enabled"] is False
    # icon off → task refused, no process started
    r = client.post("/api/claude/chat", json={"text": "salom"}, headers=ha)
    assert r.status_code == 403
    assert client.put("/api/claude/config", json={"permission_mode": "rm -rf"}, headers=ha).status_code == 400
    st = client.put("/api/claude/config", json={"permission_mode": "plan"}, headers=ha).json()
    assert st["permission_mode"] == "plan"

    # icon on → streamed run (fake CLI events)
    async def fake_run(prompt, admin):
        yield {"t": "init", "session_id": "abc", "model": "m"}
        yield {"t": "text", "text": "tayyor: " + prompt}
        yield {"t": "done", "ok": True, "text": "tayyor"}
    monkeypatch.setattr(bridge, "run", fake_run)
    client.post("/api/claude/toggle", json={"enabled": True}, headers=ha)
    r = client.post("/api/claude/chat", json={"text": "test"}, headers=ha)
    assert r.status_code == 200 and "tayyor: test" in r.text
    # /claude chat command: admin only
    r = client.post("/api/chat", json={"text": "/claude"}, headers=ha).json()
    assert "Claude" in r["reply"]
    r = client.post("/api/chat", json={"text": "/claude kod yoz"}, headers=hu).json()
    assert "faqat administrator" in r["reply"]
    client.post("/api/claude/toggle", json={"enabled": False}, headers=ha)


def test_stream_parser():
    evs = ClaudeBridge.parse({"type": "assistant", "message": {"content": [
        {"type": "text", "text": "Salom"}, {"type": "tool_use", "name": "Bash", "input": {"command": "pytest -q"}}]}})
    assert evs[0] == {"t": "text", "text": "Salom"} and evs[1]["name"] == "Bash" and "pytest" in evs[1]["input"]
    res = ClaudeBridge.parse({"type": "result", "result": "ok", "total_cost_usd": 0.01, "num_turns": 2, "session_id": "s"})
    assert res[0]["t"] == "result" and res[0]["turns"] == 2
    assert ClaudeBridge.parse({"type": "rate_limit_event"}) == []


def test_client_panel(client):
    ha, a = _reg(client, "cpadmin")
    _make_admin(client, a["id"])
    hu, _ = _reg(client, "cpuser")
    p = client.get("/api/client/panel", headers=hu).json()
    assert p["panel"]["enabled"] and p["commands"]
    cmds = [{"id": "x1", "icon": "🧪", "title": "Test", "prompt": "Salom de", "service": "chat"},
            {"id": "x2", "icon": "📈", "title": "Trading", "prompt": "Bozor", "service": "trading"}, {"title": ""}]
    r = client.put("/api/admin/config", json={"client_commands": cmds, "client_panel": {"title": "Mening AI"}}, headers=ha)
    assert r.status_code == 200 and len(r.json()["client_commands"]) == 2
    p = client.get("/api/client/panel", headers=hu).json()
    assert p["panel"]["title"] == "Mening AI" and {c["id"] for c in p["commands"]} == {"x1", "x2"}
    # service off → command hidden and refused
    uid = client.get("/api/auth/me", headers=hu).json()["id"]
    client.put(f"/api/admin/users/{uid}/policy", json={"services": {"trading": False}}, headers=ha)
    from backend.security import services
    services._cache.clear()
    p = client.get("/api/client/panel", headers=hu).json()
    assert [c["id"] for c in p["commands"]] == ["x1"]
    assert client.post("/api/client/run", json={"command_id": "x2"}, headers=hu).status_code == 404
    assert client.get("/panel").status_code == 200


def test_deploy_webhook_signature(client, monkeypatch):
    from backend.api import deploy
    from backend.config import settings
    monkeypatch.setattr(settings, "DEPLOY_WEBHOOK_SECRET", "s3cret")
    called = []

    async def fake(trigger):
        called.append(trigger)
        return {"ok": True}
    monkeypatch.setattr(deploy, "run_deploy", fake)
    body = b'{"ref": "refs/heads/main"}'
    assert client.post("/api/deploy/webhook", content=body, headers={"X-Hub-Signature-256": "sha256=bad"}).status_code == 401
    sig = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    r = client.post("/api/deploy/webhook", content=body, headers={"X-Hub-Signature-256": sig, "X-GitHub-Event": "push",
                                                                  "Content-Type": "application/json"})
    assert r.status_code == 200 and r.json()["started"]
    body2 = b'{"ref": "refs/heads/dev"}'
    sig2 = "sha256=" + hmac.new(b"s3cret", body2, hashlib.sha256).hexdigest()
    assert "skipped" in client.post("/api/deploy/webhook", content=body2, headers={"X-Hub-Signature-256": sig2}).json()


def test_mobile_pairing(client):
    import json as _json
    h, u = _reg(client, "mobuser")
    r = client.post("/api/mobile/pair-code", json={"server": "http://10.0.0.5:8000"}, headers=h).json()
    p = _json.loads(r["payload"])
    assert p == {"robin": 1, "server": "http://10.0.0.5:8000", "code": r["code"]} and "<svg" in r["qr"]
    assert client.post("/api/mobile/pair", json={"code": "wrong"}).status_code == 401
    ok = client.post("/api/mobile/pair", json={"code": r["code"], "device_name": "Pixel"}).json()
    assert ok["user"]["username"] == "mobuser"
    me = client.get("/api/auth/me", headers={"Authorization": "Bearer " + ok["token"]})
    assert me.status_code == 200
    assert client.post("/api/mobile/pair", json={"code": r["code"]}).status_code == 401     # one-time
    assert client.get("/api/mobile/info").json()["url"] == "/download/ROBIN.apk"
