"""/bot-admin: ko'prik tokeni, login, navbat, hodisalar va fayllar."""
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api import bot_admin
from backend.main import app

_TMP = Path(tempfile.mkdtemp(prefix="bot_admin_"))
bot_admin.DB_PATH = _TMP / "bot_admin.db"          # haqiqiy database/ ga tegmaydi
bot_admin.FILES_DIR = _TMP / "files"


@pytest.fixture(scope="module")
def c():
    with TestClient(app) as client:
        yield client


def B():
    return {"X-Bridge-Token": bot_admin.bridge_token()}


def test_page_and_auth_required(c):
    r = c.get("/bot-admin")
    assert r.status_code == 200 and "Bot Adminka" in r.text
    assert c.get("/bot-admin/api/state").status_code == 401
    assert c.post("/bot-admin/api/send", json={"text": "/help"}).status_code == 401
    assert c.get("/bot-admin/bridge/poll?wait=0").status_code == 403
    assert c.get("/bot-admin/bridge/poll?wait=0", headers={"X-Bridge-Token": "x"}).status_code == 403


def test_full_flow(c):
    # sozlanmagan — login 503
    assert c.post("/bot-admin/api/login", json={"login": "a", "password": "b"}).status_code == 503
    pw = bot_admin.make_password_hash("Sir-parol-123", iterations=1000)
    catalog = [{"key": "dusel", "title": "Dusel", "cmds": [{"c": "elektriklar", "d": "Excel", "h": ""}]}]
    assert c.post("/bot-admin/bridge/hello", headers=B(),
                  json={"login": "admin", "pw": pw, "catalog": catalog, "bot": {"username": "duselb1bot"}}).is_success
    assert c.post("/bot-admin/api/login", json={"login": "admin", "password": "noto'g'ri"}).status_code == 401
    r = c.post("/bot-admin/api/login", json={"login": "admin", "password": "Sir-parol-123"})
    assert r.status_code == 200

    s = c.get("/bot-admin/api/state?catalog=1").json()
    assert s["online"] is True and s["catalog"] == catalog and s["bot"]["username"] == "duselb1bot"

    assert c.post("/bot-admin/api/send", json={"text": "/elektriklar"}).is_success
    assert c.post("/bot-admin/api/send", json={"callback": "xod:r:0", "mid": 5}).is_success
    items = c.get("/bot-admin/bridge/poll?wait=0", headers=B()).json()["items"]
    assert [i["type"] for i in items] == ["text", "callback"]
    assert items[0]["text"] == "/elektriklar" and items[1]["data"] == "xod:r:0" and items[1]["mid"] == 5
    assert c.get("/bot-admin/bridge/poll?wait=0", headers=B()).json()["items"] == []   # bir marta beriladi

    f = c.post("/bot-admin/bridge/file", headers=B(), files={"file": ("hisobot.xlsx", b"PK\x03\x04data")}).json()
    assert f["name"] == "hisobot.xlsx" and f["size"] == 8
    c.post("/bot-admin/bridge/events", headers=B(), json={"events": [
        {"type": "message", "mid": 1, "html": "<b>Tayyor</b>", "file": f},
        {"type": "edit", "mid": 1, "html": "<b>Yangilandi</b>"},
        {"type": "hack", "x": 1}]})
    ev = c.get("/bot-admin/api/state").json()["events"]
    assert [e["type"] for e in ev] == ["out", "message", "edit"]      # callback — chiqmaydi, «hack» — rad
    assert c.get(f"/bot-admin/api/file/{f['id']}").content == b"PK\x03\x04data"
    assert c.get("/bot-admin/api/file/../../etc").status_code == 404

    up = c.post("/bot-admin/api/upload", files={"file": ("r.xlsx", b"abc")}, data={"caption": "/dusel"}).json()
    item = c.get("/bot-admin/bridge/poll?wait=0", headers=B()).json()["items"][0]
    assert item["type"] == "document" and item["caption"] == "/dusel"
    assert c.get(f"/bot-admin/bridge/file/{item['file']['id']}", headers=B()).content == b"abc"
    assert up["ok"]

    # parol o'zgarsa eski sessiya bekor bo'ladi
    c.post("/bot-admin/bridge/hello", headers=B(), json={"login": "admin", "pw": bot_admin.make_password_hash("yangi", 1000)})
    assert c.get("/bot-admin/api/state").status_code == 401
