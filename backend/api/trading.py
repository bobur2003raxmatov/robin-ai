"""ROBIN Trading Expert API: analysis, risk, backtest, competition, simulator, journal, approval workflow, academy."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agents.executor import ToolContext, approvals, run_agent
from backend.ai.brain import get_brain
from backend.memory.database import LessonProgress, TradeJournal, User, get_session
from backend.memory.memory import Memory
from backend.security.auth import current_user
from backend.security.services import require_service
from backend.trading import backtest, broker, indicators, market, risk
from backend.trading.lessons import CURRICULUM, find_lesson

router = APIRouter(prefix="/api/trading", tags=["trading"], dependencies=[Depends(require_service("trading"))])


@router.get("/analyze")
async def analyze(symbol: str, interval: str = "1h", user: User = Depends(current_user)):
    try:
        df = await market.candles(symbol, interval, 500)
    except Exception as e:
        raise HTTPException(400, f"Ma'lumot olinmadi: {e}") from e
    a = indicators.full_analysis(df)
    a["candles"] = [[str(t), o, h, l, c] for t, o, h, l, c in
                    df[["time", "open", "high", "low", "close"]].tail(150).itertuples(index=False)]
    return a


@router.get("/ai-analysis")
async def ai_analysis(symbol: str, interval: str = "1h", user: User = Depends(current_user)):
    """Market Researcher + Trading expert: multi-scenario analysis with confidence and invalidation."""
    brain = await get_brain(user.id)
    ctx = ToolContext(user_id=user.id, brain=brain, memory=Memory(user.id, brain.keys))
    res = await run_agent(ctx, f"{symbol} ni {interval} va yuqori taymfreymlarda to'liq tahlil qil (market_analyze "
                               f"multi_timeframe), kerak bo'lsa so'nggi yangiliklarni web_search bilan tekshir. Natija: "
                               f"bozor holati, 2-3 ssenariy (ehtimollik %), kirish zonasi, SL, TP, R:R, invalidatsiya, "
                               f"ishonchlilik va noaniqliklar. Savdo ochma.", agent="trader")
    return {"analysis": res["text"], "steps": res["steps"]}


class RiskIn(BaseModel):
    balance: float
    risk_pct: float = 1.0
    entry: float
    stop_loss: float
    take_profit: float | None = None


@router.post("/risk")
async def risk_calc(data: RiskIn, user: User = Depends(current_user)):
    size = risk.position_size(data.balance, data.risk_pct, data.entry, data.stop_loss)
    rr = risk.risk_reward(data.entry, data.stop_loss, data.take_profit) if data.take_profit else None
    return {**size, "rr": rr}


@router.get("/backtest")
async def run_backtest(symbol: str, strategy: str = "ema_cross", interval: str = "1h", bars: int = 1000,
                       user: User = Depends(current_user)):
    df = await market.candles(symbol, interval, bars)
    if strategy == "competition":
        return backtest.competition(df)
    if strategy not in backtest.STRATEGIES:
        raise HTTPException(400, "Noma'lum strategiya")
    return backtest.backtest(df, strategy)


@router.get("/strategies")
async def strategies():
    return [{"id": k, "description": v[1]} for k, v in backtest.STRATEGIES.items()]


class PlanIn(BaseModel):
    symbol: str
    side: str
    qty: float
    entry: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    mode: str = "paper"   # paper | live
    strategy: str = ""
    reason: str = ""
    emotion: str = ""


@router.post("/plan")
async def plan_trade(data: PlanIn, user: User = Depends(current_user)):
    """Trading Approval Workflow: analysis → risk check → owner approves → executor → journal."""
    plan = data.model_dump()
    plan["entry"] = plan["entry"] or await market.price(data.symbol)
    chk = await broker.check_plan(user.id, plan)
    if not chk["ok"]:
        return {"ok": False, **chk}
    if data.mode == "paper":
        return await broker.paper_open(user.id, plan)
    from backend.security.services import allowed, denied_text
    if not await allowed(user.id, "trading_live"):
        raise HTTPException(403, denied_text("trading_live"))
    brain = await get_brain(user.id)
    ctx = ToolContext(user_id=user.id, brain=brain, memory=Memory(user.id, brain.keys))
    approved = await approvals.request(ctx, "live_trade", plan, "critical",
                                       f"REAL savdo: {data.side.upper()} {data.qty} {data.symbol} @~{plan['entry']} "
                                       f"SL {data.stop_loss} TP {data.take_profit}", timeout=600)
    if not approved:
        return {"ok": False, "status": "rejected"}
    return await broker.live_order(user.id, plan)


@router.post("/close/{trade_id}")
async def close(trade_id: str, user: User = Depends(current_user)):
    return await broker.close_trade(user.id, trade_id)


@router.get("/account")
async def account(user: User = Depends(current_user)):
    acc = await broker.account(user.id)
    return {"balance": acc.balance, "start_balance": acc.start_balance, "day_start_balance": acc.day_start_balance,
            "limits": await broker.limits(user.id)}


@router.post("/account/reset")
async def reset_account(balance: float = 10000, user: User = Depends(current_user),
                        db: AsyncSession = Depends(get_session)):
    acc = await broker.account(user.id)
    acc = await db.get(type(acc), user.id)
    acc.balance = acc.start_balance = acc.day_start_balance = balance
    await db.commit()
    return {"ok": True, "balance": balance}


@router.get("/journal")
async def journal(user: User = Depends(current_user), db: AsyncSession = Depends(get_session)):
    rows = (await db.scalars(select(TradeJournal).where(TradeJournal.user_id == user.id)
                             .order_by(desc(TradeJournal.opened_at)).limit(300))).all()
    closed = [t for t in rows if t.status == "closed"]
    wins = [t for t in closed if t.pnl > 0]
    return {"stats": {"total": len(rows), "closed": len(closed),
                      "win_rate": round(len(wins) / len(closed) * 100, 1) if closed else 0,
                      "pnl": round(sum(t.pnl for t in closed), 2),
                      "avg_win": round(sum(t.pnl for t in wins) / len(wins), 2) if wins else 0,
                      "avg_loss": round(sum(t.pnl for t in closed if t.pnl <= 0) / max(1, len(closed) - len(wins)), 2)},
            "trades": [{"id": t.id, "mode": t.mode, "symbol": t.symbol, "side": t.side, "qty": t.qty,
                        "entry": t.entry, "exit": t.exit, "sl": t.stop_loss, "tp": t.take_profit, "pnl": t.pnl,
                        "status": t.status, "strategy": t.strategy, "reason": t.reason,
                        "mentor_review": t.mentor_review, "opened_at": t.opened_at.isoformat()} for t in rows]}


@router.post("/mentor/{trade_id}")
async def mentor(trade_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_session)):
    """AI Mentor: reviews a trade and explains mistakes (psychology coach included)."""
    t = await db.get(TradeJournal, trade_id)
    if not t or t.user_id != user.id:
        raise HTTPException(404)
    brain = await get_brain(user.id)
    ctx = ToolContext(user_id=user.id, brain=brain, memory=Memory(user.id, brain.keys))
    res = await run_agent(ctx, f"AI Mentor sifatida ushbu savdoni tekshir: {t.symbol} {t.side} qty={t.qty} "
                               f"entry={t.entry} exit={t.exit} SL={t.stop_loss} TP={t.take_profit} PnL={t.pnl} "
                               f"strategiya={t.strategy} sabab='{t.reason}' kayfiyat='{t.emotion}'. Kerak bo'lsa "
                               f"market_analyze bilan bozorni ko'r. Nima to'g'ri, nima xato, risk menejmenti, psixologiya, "
                               f"keyingi safar nima qilish kerak — aniq va o'rgatuvchi qilib tushuntir.", agent="trader")
    t.mentor_review = res["text"]
    await db.commit()
    return {"review": res["text"]}


@router.get("/academy")
async def academy(user: User = Depends(current_user), db: AsyncSession = Depends(get_session)):
    prog = {p.lesson_id: {"score": p.score, "completed": p.completed}
            for p in (await db.scalars(select(LessonProgress).where(LessonProgress.user_id == user.id))).all()}
    return {"curriculum": CURRICULUM, "progress": prog}


@router.get("/academy/{lesson_id}")
async def lesson(lesson_id: str, user: User = Depends(current_user)):
    les = find_lesson(lesson_id)
    if not les:
        raise HTTPException(404)
    brain = await get_brain(user.id)
    if not brain.available:
        return {"lesson": les, "content": "\n".join(f"• {p}" for p in les["points"])}
    r = await brain.complete("Sen ROBIN Trading ustozisan. Darsni o'zbek tilida, oddiy tilda, misollar, raqamli "
                             "hisob-kitoblar va amaliy topshiriq bilan tushuntir. Markdown ishlat.",
                             [{"role": "user", "content": f"Dars: {les['title']} ({les['level']}). Mavzular: "
                               f"{', '.join(les['points'])}. Oxirida 3 ta savoldan iborat test ber."}], max_tokens=3000)
    return {"lesson": les, "content": r.text}


class QuizIn(BaseModel):
    answers: list[str]


@router.post("/academy/{lesson_id}/quiz")
async def quiz(lesson_id: str, data: QuizIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_session)):
    les = find_lesson(lesson_id)
    if not les:
        raise HTTPException(404)
    brain = await get_brain(user.id)
    feedback = ""
    score = 0.0
    if brain.available:
        res = await brain.ask_json('Javoblarni baholang. JSON: {"score": 0-100, "feedback": "har bir xatoni tushuntir"}',
                                   f"Dars: {les['title']}\nSavollar/kalit: {les['quiz']}\nFoydalanuvchi javoblari: "
                                   f"{data.answers}", fast=False)
        score, feedback = float(res.get("score", 0)), res.get("feedback", "")
    row = await db.scalar(select(LessonProgress).where(LessonProgress.user_id == user.id,
                                                       LessonProgress.lesson_id == lesson_id))
    if not row:
        row = LessonProgress(user_id=user.id, lesson_id=lesson_id)
        db.add(row)
    row.score, row.completed = max(row.score or 0, score), score >= 70
    await db.commit()
    return {"score": score, "feedback": feedback, "completed": row.completed}
