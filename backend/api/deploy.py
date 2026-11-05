"""Auto-deploy: GitHub/GitLab push webhook → git pull → pip install (if requirements changed) → restart.

GitHub → repo → Settings → Webhooks → Payload URL: https://<host>/api/deploy/webhook,
Content type: application/json, Secret: DEPLOY_WEBHOOK_SECRET, events: "Just the push event".
Restart: with DEPLOY_RESTART=true the process exits after a successful update and systemd / Docker /
the hosting platform starts it again with the new code.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import subprocess
import sys
import time

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.config import BASE_DIR, settings
from backend.memory.database import User
from backend.security.auth import admin_user

router = APIRouter(prefix="/api/deploy", tags=["deploy"])
STATE: dict = {"running": False, "last": None, "log": []}


def _git(*args: str, timeout: int = 120) -> tuple[int, str]:
    try:
        r = subprocess.run(["git", *args], cwd=BASE_DIR, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def verify(secret: str, body: bytes, sig256: str = "", gitlab_token: str = "") -> bool:
    if not secret:
        return False
    if gitlab_token:
        return hmac.compare_digest(gitlab_token, secret)
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig256 or "")


def _update() -> dict:
    log: list[str] = []
    code, before = _git("rev-parse", "HEAD")
    code, out = _git("pull", "--ff-only", "origin", settings.DEPLOY_BRANCH, timeout=300)
    log.append("$ git pull\n" + out)
    if code:
        return {"ok": False, "log": log}
    _, after = _git("rev-parse", "HEAD")
    if before == after:
        return {"ok": True, "changed": False, "log": log}
    _, files = _git("diff", "--name-only", before, after)
    if "requirements.txt" in files.split():
        r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt"], cwd=BASE_DIR,
                           capture_output=True, text=True, timeout=900)
        log.append("$ pip install\n" + (r.stdout + r.stderr)[-3000:])
        if r.returncode:
            return {"ok": False, "log": log}
    return {"ok": True, "changed": True, "commit": after[:10], "log": log}


async def run_deploy(trigger: str) -> dict:
    if STATE["running"]:
        return {"ok": False, "error": "Deploy allaqachon ishlayapti"}
    STATE["running"] = True
    try:
        res = await asyncio.get_running_loop().run_in_executor(None, _update)
        res.update({"at": time.time(), "trigger": trigger})
        STATE["last"] = res
        if res.get("ok") and res.get("changed") and settings.DEPLOY_RESTART:
            asyncio.get_running_loop().call_later(1.5, os._exit, 0)   # supervisor restarts us with the new code
        return res
    finally:
        STATE["running"] = False


@router.post("/webhook")
async def webhook(request: Request):
    body = await request.body()
    if not verify(settings.DEPLOY_WEBHOOK_SECRET, body, request.headers.get("X-Hub-Signature-256", ""),
                  request.headers.get("X-Gitlab-Token", "")):
        raise HTTPException(401, "Webhook imzosi noto'g'ri yoki DEPLOY_WEBHOOK_SECRET sozlanmagan")
    event = request.headers.get("X-GitHub-Event") or request.headers.get("X-Gitlab-Event", "push")
    if event == "ping":
        return {"ok": True, "pong": True}
    try:
        ref = (await request.json()).get("ref", "")
    except ValueError:
        ref = ""
    if ref and ref != f"refs/heads/{settings.DEPLOY_BRANCH}":
        return {"ok": True, "skipped": ref}
    asyncio.create_task(run_deploy("webhook"))
    return {"ok": True, "started": True}


@router.get("/status")
async def status(admin: User = Depends(admin_user)):
    _, head = _git("log", "-1", "--format=%h %s (%cr)")
    _, remote = _git("remote", "get-url", "origin")
    return {"configured": bool(settings.DEPLOY_WEBHOOK_SECRET), "branch": settings.DEPLOY_BRANCH,
            "restart": settings.DEPLOY_RESTART, "head": head, "remote": remote if "fatal" not in remote else "",
            "running": STATE["running"], "last": STATE["last"]}


@router.post("/run")
async def manual(admin: User = Depends(admin_user)):
    return await run_deploy("admin")
