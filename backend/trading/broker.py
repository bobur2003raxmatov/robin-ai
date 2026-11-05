"""Trading Executor: paper (virtual money with real prices) and live Binance (testnet by default).

Live orders are ONLY placed through the Approval workflow (see agents/executor.py → approvals).
Protections: daily loss limit, max position, duplicate-order guard, encrypted API keys, emergency STOP.
"""
from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import func, select

from backend.config import settings
from backend.memory.database import PaperAccount, SessionLocal, TradeJournal, now
from backend.memory.settings_store import get_setting
from backend.security.permissions import emergency
from backend.trading import market
from backend.trading.risk import evaluate_plan

_recent_orders: dict[str, float] = {}  # duplicate guard: hash -> ts


def _dup_key(user_id: str, plan: dict) -> str:
    return f"{user_id}:{plan['symbol']}:{plan['side']}:{round(plan['qty'], 6)}"


async def account(user_id: str) -> PaperAccount:
    async with SessionLocal() as db:
        acc = await db.get(PaperAccount, user_id)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if not acc:
            acc = PaperAccount(user_id=user_id, day=today)
            db.add(acc)
        if acc.day != today:
            acc.day, acc.day_start_balance, acc.trading_locked = today, acc.balance, False
        await db.commit()
        await db.refresh(acc)
        return acc


async def limits(user_id: str) -> dict:
    t = await get_setting(user_id, "trading")
    return {"max_daily_loss_pct": float(t.get("max_daily_loss_pct", settings.MAX_DAILY_LOSS_PCT)),
            "max_position_pct": float(t.get("max_position_pct", settings.MAX_POSITION_PCT)),
            "max_risk_per_trade_pct": float(t.get("max_risk_per_trade_pct", settings.MAX_RISK_PER_TRADE_PCT))}


async def check_plan(user_id: str, plan: dict) -> dict:
    acc = await account(user_id)
    async with SessionLocal() as db:
        open_n = await db.scalar(select(func.count()).select_from(TradeJournal).where(
            TradeJournal.user_id == user_id, TradeJournal.status == "open"))
    day_pnl = (acc.balance - acc.day_start_balance) / acc.day_start_balance * 100 if acc.day_start_balance else 0
    res = evaluate_plan(dict(plan), acc.balance, await limits(user_id), day_pnl, open_n or 0)
    if emergency.active(user_id):
        res["ok"] = False
        res["blocks"].append("Favqulodda STOP faol")
    k = _dup_key(user_id, plan)
    if time.time() - _recent_orders.get(k, 0) < 60:
        res["ok"] = False
        res["blocks"].append("Takroriy buyurtma (60 soniya ichida aynan shu buyurtma berilgan)")
    return res


async def paper_open(user_id: str, plan: dict) -> dict:
    chk = await check_plan(user_id, plan)
    if not chk["ok"]:
        return {"ok": False, **chk}
    px = plan.get("entry") or await market.price(plan["symbol"])
    _recent_orders[_dup_key(user_id, plan)] = time.time()
    async with SessionLocal() as db:
        t = TradeJournal(user_id=user_id, mode="paper", symbol=plan["symbol"].upper(), side=plan["side"],
                         qty=plan["qty"], entry=px, stop_loss=plan.get("stop_loss"),
                         take_profit=plan.get("take_profit"), strategy=plan.get("strategy", ""),
                         reason=plan.get("reason", ""), emotion=plan.get("emotion", ""), status="open",
                         client_order_id=uuid.uuid4().hex[:20])
        db.add(t)
        await db.commit()
        return {"ok": True, "trade_id": t.id, "entry": px, "warnings": chk["warnings"]}


async def close_trade(user_id: str, trade_id: str, exit_price: float | None = None) -> dict:
    async with SessionLocal() as db:
        t = await db.get(TradeJournal, trade_id)
        if not t or t.user_id != user_id or t.status != "open":
            return {"ok": False, "error": "Ochiq savdo topilmadi"}
        px = exit_price or await market.price(t.symbol)
        direction = 1 if t.side == "buy" else -1
        t.exit, t.pnl, t.status, t.closed_at = px, round((px - t.entry) * t.qty * direction, 2), "closed", now()
        if t.mode == "paper":
            acc = await db.get(PaperAccount, user_id)
            if acc:
                acc.balance = round(acc.balance + t.pnl, 2)
        await db.commit()
        return {"ok": True, "trade_id": t.id, "exit": px, "pnl": t.pnl}


async def check_stops(user_id: str) -> list[dict]:
    """Paper simulator: close positions whose SL/TP was hit (called by scheduler)."""
    closed = []
    async with SessionLocal() as db:
        open_trades = (await db.scalars(select(TradeJournal).where(TradeJournal.user_id == user_id,
                                                                  TradeJournal.status == "open",
                                                                  TradeJournal.mode == "paper"))).all()
    for t in open_trades:
        try:
            px = await market.price(t.symbol)
        except Exception:
            continue
        hit = None
        if t.side == "buy":
            if t.stop_loss and px <= t.stop_loss: hit = t.stop_loss
            elif t.take_profit and px >= t.take_profit: hit = t.take_profit
        else:
            if t.stop_loss and px >= t.stop_loss: hit = t.stop_loss
            elif t.take_profit and px <= t.take_profit: hit = t.take_profit
        if hit:
            closed.append(await close_trade(user_id, t.id, hit) | {"symbol": t.symbol})
    return closed


# ---------------------------------------------------------------- live (Binance)
async def _binance_keys(user_id: str) -> tuple[str, str]:
    keys = await get_setting(user_id, "api_keys")
    return (keys.get("binance_key") or settings.BINANCE_API_KEY,
            keys.get("binance_secret") or settings.BINANCE_API_SECRET)


async def live_order(user_id: str, plan: dict) -> dict:
    """Executed only after explicit owner approval."""
    chk = await check_plan(user_id, plan)
    if not chk["ok"]:
        return {"ok": False, **chk}
    key, secret = await _binance_keys(user_id)
    if not key or not secret:
        return {"ok": False, "error": "Broker API kalitlari sozlanmagan (Dashboard → Trading)"}
    base = "https://testnet.binance.vision" if settings.BINANCE_TESTNET else "https://api.binance.com"
    src, sym = market.classify(plan["symbol"])
    if src != "binance":
        return {"ok": False, "error": "Hozircha live ijro faqat Binance kripto juftliklari uchun ulangan"}
    coid = "robin_" + uuid.uuid4().hex[:16]
    params = {"symbol": sym, "side": plan["side"].upper(), "type": "MARKET",
              "quantity": f"{plan['qty']:.6f}".rstrip("0").rstrip("."), "newClientOrderId": coid,
              "timestamp": int(time.time() * 1000), "recvWindow": 5000}
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    sig = hmac.new(secret.encode(), qs.encode(), hashlib.sha256).hexdigest()
    _recent_orders[_dup_key(user_id, plan)] = time.time()
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(f"{base}/api/v3/order?{qs}&signature={sig}", headers={"X-MBX-APIKEY": key})
    if r.status_code >= 400:
        return {"ok": False, "error": f"Broker xatosi: {r.text[:300]}"}
    data = r.json()
    fills = data.get("fills") or []
    px = float(fills[0]["price"]) if fills else plan.get("entry", 0)
    async with SessionLocal() as db:
        t = TradeJournal(user_id=user_id, mode="live", symbol=sym, side=plan["side"], qty=plan["qty"], entry=px,
                         stop_loss=plan.get("stop_loss"), take_profit=plan.get("take_profit"),
                         strategy=plan.get("strategy", ""), reason=plan.get("reason", ""), status="open",
                         client_order_id=coid)
        db.add(t)
        await db.commit()
    return {"ok": True, "trade_id": t.id, "order": data, "testnet": settings.BINANCE_TESTNET}
