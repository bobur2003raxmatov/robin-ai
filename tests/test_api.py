"""API smoke tests: auth isolation, settings, commands, memory, approvals, emergency stop (no AI keys needed)."""
import pytest
from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _register(c, name):
    r = c.post("/api/auth/register", json={"username": name, "password": "secret123", "full_name": name.title()})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}, r.json()["user"]


def test_full_flow(client):
    import asyncio
    from sqlalchemy import func, select
    from backend.memory.database import SessionLocal, User

    async def count():
        async with SessionLocal() as db:
            return await db.scalar(select(func.count()).select_from(User))
    first = client.portal.call(count) == 0 if hasattr(client, "portal") else None
    h1, u1 = _register(client, "alice")
    h2, u2 = _register(client, "bob")
    if first:
        assert u1["is_admin"]                              # first user = admin
    assert not u2["is_admin"]
    assert u1["id"] != u2["id"] and len(u1["id"]) == 32   # auto ID

    async def promote():
        async with SessionLocal() as db:
            u = await db.get(User, u1["id"])
            u.is_admin = True
            await db.commit()
    client.portal.call(promote)

    assert client.get("/api/auth/me").status_code == 401   # login required
    assert client.post("/api/auth/login", json={"username": "alice", "password": "wrong-pass"}).status_code == 401

    # settings online + secrets masked
    r = client.put("/api/settings/api_keys", headers=h1, json={"openai": "sk-test-1234567890abcdef"})
    assert r.status_code == 200
    s = client.get("/api/settings", headers=h1).json()
    assert s["api_keys"]["openai"].startswith("sk-t") and "1234567890" not in s["api_keys"]["openai"]
    client.put("/api/settings/api_keys", headers=h1, json={"openai": ""})

    # commands per user
    cmd = {"name": "Ertalabki ish", "triggers": ["ishni boshla"], "steps": [{"tool": "wait", "args": {"seconds": 0}}]}
    assert client.post("/api/commands", headers=h1, json=cmd).status_code == 200
    assert client.post("/api/commands", headers=h1, json=cmd).status_code == 409
    assert len(client.get("/api/commands", headers=h1).json()) == 1
    assert client.get("/api/commands", headers=h2).json() == []          # isolation
    bad = {"name": "x", "steps": [{"tool": "hack_the_planet"}]}
    assert client.post("/api/commands", headers=h1, json=bad).status_code == 400

    # chat without AI keys → saved command still runs by voice phrase
    r = client.post("/api/chat", headers=h1, json={"text": "ROBIN, ishni boshla"}).json()
    assert r["meta"].get("command") == "Ertalabki ish"
    r = client.post("/api/chat", headers=h1, json={"text": "salom"}).json()
    assert "API" in r["reply"]

    # memory isolation
    client.post("/api/memory", headers=h1, json={"content": "Marketplace loyihasi Django'da", "kind": "project",
                                                 "subject": "Marketplace"})
    assert len(client.get("/api/memory", headers=h1).json()) == 1
    assert client.get("/api/memory", headers=h2).json() == []
    found = client.get("/api/memory/search?q=marketplace", headers=h1).json()
    assert found["memories"]

    # reminders
    assert client.post("/api/reminders", headers=h1, json={"title": "Uchrashuv", "due_at": "2030-01-01T10:00",
                                                           "kind": "meeting"}).status_code == 200
    assert len(client.get("/api/reminders", headers=h1).json()) == 1

    # emergency stop
    assert client.post("/api/emergency/stop", headers=h1).json()["stopped"]
    r = client.post("/api/chat", headers=h1, json={"text": "salom"}).json()
    assert "STOP" in r["reply"]
    client.post("/api/emergency/resume", headers=h1)

    # admin only
    assert client.get("/api/system/users", headers=h2).status_code == 403
    assert len(client.get("/api/system/users", headers=h1).json()) >= 2
    assert client.get("/api/system/activity", headers=h1).json()

    # dashboard pages served
    assert client.get("/").status_code == 200 and client.get("/widget").status_code == 200
    assert len(client.get("/api/tools", headers=h1).json()) >= 50


def test_notes_and_download(client):
    import io
    import json
    import zipfile
    r = client.post("/api/auth/register", json={"username": "noteuser", "password": "secret123"})
    h = {"Authorization": "Bearer " + r.json()["token"]}
    # system guides from /notes/*.md are listed, user notes are private
    items = client.get("/api/notes", headers=h).json()["items"]
    assert any(i.get("system") for i in items)
    n = client.post("/api/notes", headers=h, json={"title": "Test qayd", "body": "**salom**"}).json()
    assert client.put(f"/api/notes/{n['id']}", headers=h, json={"title": "Yangi", "body": "x", "pinned": True}).json()["pinned"]
    assert any(i["title"] == "Yangi" for i in client.get("/api/notes?q=Yangi", headers=h).json()["items"])
    # new command → ROBIN writes a note automatically
    client.post("/api/commands", headers=h, json={"name": "Kofe", "steps": [{"tool": "wait", "args": {"seconds": 0}}]})
    cmds = client.get("/api/notes?category=command", headers=h).json()["items"]
    assert any("Kofe" in i["title"] and i["auto"] for i in cmds)
    assert "# Yangi" in client.get("/api/notes/export.md", headers=h).text
    # download app: info + QR + pre-configured desktop package
    info = client.get("/api/apps/info", headers=h).json()
    assert info["mobile_qr"].lstrip().startswith("<") and "svg" in info["mobile_qr"][:200]
    link = client.post("/api/apps/desktop-link", headers=h, json={"name": "Test PC", "base": "http://10.0.0.5:8000"}).json()
    rid = link["url"].rsplit("/", 1)[1]
    z = zipfile.ZipFile(io.BytesIO(client.get(f"/download/desktop/{rid}").content))
    names = z.namelist()
    assert "ROBIN-Desktop/robin_agent.py" in names and "ROBIN-Desktop/backend/agents/computer.py" in names
    conf = json.loads(z.read("ROBIN-Desktop/robin_config.json"))
    assert conf["server"] == "http://10.0.0.5:8000" and "." in conf["device_token"]
    # the device token can be traded for a login token (widget without password)
    tok = client.post("/api/devices/session", json={"device_token": conf["device_token"]}).json()["token"]
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer " + tok}).json()["username"] == "noteuser"
    assert client.post("/api/devices/session", json={"device_token": "x.bad"}).status_code == 401
    assert client.get("/download/desktop/nonexistent").status_code == 410
