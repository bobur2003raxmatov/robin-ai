"""Admin panel, per-user service access, limits, registration control + Uzbek speech preparation."""
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.voice.text_to_speech import (apply_lexicon, clean_for_speech, cyr_to_lat, edge_params, num_to_uz,
                                          numbers_to_uz, ordinal_uz, prepare_uz, split_segments)


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


def test_admin_services_and_limits(client):
    ha, a = _reg(client, "boss1")
    _make_admin(client, a["id"])
    hu, u = _reg(client, "worker1")

    assert client.get("/api/admin/users", headers=hu).status_code == 403          # not admin
    users = client.get("/api/admin/users", headers=ha).json()
    assert any(x["id"] == u["id"] for x in users)

    # disable trading + files for the worker
    r = client.put(f"/api/admin/users/{u['id']}/policy", headers=ha,
                   json={"services": {"trading": False, "files": False, "notes": False}, "limits": {"daily_messages": 2}})
    assert r.status_code == 200 and r.json()["services"]["trading"] is False
    assert client.get("/api/trading/account", headers=hu).status_code == 403
    assert client.get("/api/notes", headers=hu).status_code == 403
    s = client.get("/api/settings", headers=hu).json()
    assert s["policy"]["services"]["trading"] is False
    assert s["permissions"]["files_read"] is False and s["permissions"]["trading_paper"] is False
    assert "files_write" in s["policy"]["locked_modules"]
    # user can't unlock a module the admin locked, nor edit the policy itself
    client.put("/api/settings/permissions", headers=hu, json={"files_read": True})
    assert client.get("/api/settings", headers=hu).json()["permissions"]["files_read"] is False
    assert client.put("/api/settings/admin_policy", headers=hu, json={"services": {"trading": True}}).status_code == 404
    # admin is never restricted
    assert client.get("/api/trading/account", headers=ha).status_code == 200

    # daily limit: 2 messages (no AI key → commands-only replies, still counted)
    for _ in range(2):
        assert client.post("/api/chat", headers=hu, json={"text": "salom"}).status_code == 200
    r = client.post("/api/chat", headers=hu, json={"text": "salom"}).json()
    assert "limit" in r["reply"].lower() and r["meta"].get("blocked")

    # chat disabled entirely
    client.put(f"/api/admin/users/{u['id']}/policy", headers=ha, json={"services": {"chat": False}})
    assert client.post("/api/chat", headers=hu, json={"text": "salom"}).status_code == 403

    # reset password → old sessions die
    pw = client.post(f"/api/admin/users/{u['id']}/password", headers=ha, json={}).json()["password"]
    assert client.get("/api/auth/me", headers=hu).status_code == 401
    r = client.post("/api/auth/login", json={"username": "worker1", "password": pw})
    assert r.status_code == 200
    hu = {"Authorization": "Bearer " + r.json()["token"]}

    # block → login refused
    assert client.put(f"/api/admin/users/{u['id']}", headers=ha, json={"is_active": False}).status_code == 200
    assert client.post("/api/auth/login", json={"username": "worker1", "password": pw}).status_code == 403
    # admin can't block / demote themselves
    assert client.put(f"/api/admin/users/{a['id']}", headers=ha, json={"is_active": False}).status_code == 400
    client.put(f"/api/admin/users/{u['id']}", headers=ha, json={"is_active": True})


def test_registration_control_and_create(client):
    ha, a = _reg(client, "boss2")
    _make_admin(client, a["id"])
    assert client.put("/api/admin/config", headers=ha,
                      json={"registration_open": False, "default_services": {"trading_live": False}}).status_code == 200
    assert client.get("/api/auth/config").json()["registration_open"] is False
    r = client.post("/api/auth/register", json={"username": "stranger", "password": "secret123"})
    assert r.status_code == 403
    r = client.post("/api/admin/users", headers=ha, json={"username": "invited", "full_name": "Mehmon"})
    assert r.status_code == 200 and len(r.json()["password"]) >= 8
    pol = client.get(f"/api/admin/users/{r.json()['id']}/policy", headers=ha).json()
    assert pol["services"]["trading_live"] is False                    # default for new users applied
    ov = client.get("/api/admin/overview", headers=ha).json()
    assert ov["users"] >= 3 and len(ov["chart"]) == 14
    client.put("/api/admin/config", headers=ha, json={"registration_open": True, "default_services": {"trading_live": True}})


def test_login_bruteforce_lock(client):
    _reg(client, "victim1")
    codes = [client.post("/api/auth/login", json={"username": "victim1", "password": "nope-nope"}).status_code
             for _ in range(6)]
    assert codes[:5] == [401] * 5 and codes[5] == 429


# ------------------------------------------------------------- Uzbek speech preparation
def test_uzbek_numbers():
    assert num_to_uz(0) == "nol"
    assert num_to_uz(15) == "oʻn besh"
    assert num_to_uz(1250) == "ming ikki yuz ellik"
    assert num_to_uz(2026) == "ikki ming yigirma olti"
    assert ordinal_uz(5) == "beshinchi" and ordinal_uz(50) == "elliginchi" and ordinal_uz(2) == "ikkinchi"
    t = numbers_to_uz("5-noyabr soat 15:30 da, 12,5% va $100")
    assert "beshinchi noyabr" in t and "oʻn besh oʻttiz" in t and "oʻn ikki butun oʻndan besh foiz" in t
    assert "yuz dollar" in t
    assert "beshdan oʻngacha" in numbers_to_uz("5-10 daqiqa")


def test_uzbek_pronunciation_pipeline():
    assert cyr_to_lat("Ўзбекистон гўзал") == "Oʻzbekiston goʻzal"
    assert "Eksel" in apply_lexicon("Excel faylni och") and "pe-de-ef" in apply_lexicon("PDF")
    assert apply_lexicon("DIQQAT") == "Diqqat"                          # not spelled letter by letter
    assert apply_lexicon("Sardor keldi", {"sardor": "Sardorbek"}).startswith("Sardorbek")
    t = prepare_uz("O'zbekiston g'alaba")
    assert "Oʻzbekiston" in t and "gʻalaba" in t
    c = clean_for_speech("## Natija\n- **bir**\n- ikki\n```py\nx=1\n```\nhttps://x.uz 🎉")
    assert "**" not in c and "https" not in c and "kod ekranda" in c and "🎉" not in c
    assert [s[0] for s in split_segments("Salom do'stim. Привет, как дела? Yaxshi.", "uz")] == ["uz", "ru", "uz"]
    assert edge_params({"rate": "500", "pitch": "-9Hz"}) == {"rate": "+100%", "pitch": "-9Hz", "volume": "+0%"}
