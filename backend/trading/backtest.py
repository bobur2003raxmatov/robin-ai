"""Backtesting engine + built-in strategies + Strategy Competition."""
from __future__ import annotations

import numpy as np
import pandas as pd

from backend.trading.indicators import atr, bollinger, ema, macd, rsi


def sig_ema_cross(df, fast=20, slow=50, **_):
    f, s = ema(df["close"], fast), ema(df["close"], slow)
    return np.where(f > s, 1, -1)


def sig_rsi_reversion(df, low=30, high=70, n=14, **_):
    r = rsi(df["close"], n)
    pos, out = 0, []
    for v in r:
        if v < low: pos = 1
        elif v > high: pos = 0
        out.append(pos)
    return np.array(out)


def sig_macd(df, **_):
    m, s, _h = macd(df["close"])
    return np.where(m > s, 1, -1)


def sig_bollinger_breakout(df, n=20, k=2.0, **_):
    u, mid, l = bollinger(df["close"], n, k)
    pos, out = 0, []
    for c, uu, mm in zip(df["close"], u, mid):
        if not np.isnan(uu) and c > uu: pos = 1
        elif not np.isnan(mm) and c < mm: pos = 0
        out.append(pos)
    return np.array(out)


def sig_trend_pullback(df, **_):
    e50, e200, r = ema(df["close"], 50), ema(df["close"], 200), rsi(df["close"])
    pos, out = 0, []
    for c, a, b, rv in zip(df["close"], e50, e200, r):
        if a > b and rv < 45: pos = 1
        elif rv > 70 or c < b: pos = 0
        out.append(pos)
    return np.array(out)


STRATEGIES = {
    "ema_cross": (sig_ema_cross, "EMA20/EMA50 kesishuvi (trend following, long/short)"),
    "rsi_reversion": (sig_rsi_reversion, "RSI <30 da sotib olish, >70 da chiqish (mean reversion)"),
    "macd": (sig_macd, "MACD signal chizig'i kesishuvi"),
    "bollinger_breakout": (sig_bollinger_breakout, "Bollinger yuqori chizig'i yorib o'tilishi"),
    "trend_pullback": (sig_trend_pullback, "EMA50>EMA200 trendida RSI pullback"),
}


def backtest(df: pd.DataFrame, strategy: str = "ema_cross", fee_pct: float = 0.1, params: dict | None = None,
             initial: float = 10000.0) -> dict:
    fn = STRATEGIES[strategy][0]
    pos = pd.Series(fn(df, **(params or {})), index=df.index).shift(1).fillna(0)  # no look-ahead
    ret = df["close"].pct_change().fillna(0)
    trades_mask = pos.diff().abs().fillna(0)
    strat = pos * ret - trades_mask * fee_pct / 100
    equity = initial * (1 + strat).cumprod()
    dd = equity / equity.cummax() - 1
    # trade list
    trades, entry_i, side = [], None, 0
    for i in range(1, len(pos)):
        if pos.iloc[i] != pos.iloc[i - 1]:
            if entry_i is not None and side != 0:
                pnl = (df["close"].iloc[i] / df["close"].iloc[entry_i] - 1) * side * 100 - fee_pct * 2
                trades.append(pnl)
            entry_i, side = i, pos.iloc[i]
    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]
    periods = len(df)
    std = strat.std()
    sharpe = float(strat.mean() / std * np.sqrt(252 if periods < 3000 else 365 * 24)) if std > 0 else 0.0
    return {"strategy": strategy, "description": STRATEGIES[strategy][1], "bars": periods,
            "from": str(df["time"].iloc[0]), "to": str(df["time"].iloc[-1]),
            "total_return_pct": round((equity.iloc[-1] / initial - 1) * 100, 2),
            "buy_hold_pct": round((df["close"].iloc[-1] / df["close"].iloc[0] - 1) * 100, 2),
            "max_drawdown_pct": round(float(dd.min()) * 100, 2), "sharpe": round(sharpe, 2),
            "trades": len(trades), "win_rate_pct": round(len(wins) / len(trades) * 100, 1) if trades else 0,
            "avg_win_pct": round(float(np.mean(wins)), 2) if wins else 0,
            "avg_loss_pct": round(float(np.mean(losses)), 2) if losses else 0,
            "profit_factor": round(sum(wins) / abs(sum(losses)), 2) if losses and sum(losses) else None,
            "final_equity": round(float(equity.iloc[-1]), 2),
            "equity_curve": [round(float(v), 2) for v in equity.iloc[:: max(1, len(equity) // 120)]],
            "note": "O'tgan natijalar kelajakni kafolatlamaydi. Komissiya hisobga olingan, slippage yo'q."}


def competition(df: pd.DataFrame, fee_pct: float = 0.1) -> dict:
    res = [backtest(df, s, fee_pct) for s in STRATEGIES]
    for r in res:
        r.pop("equity_curve", None)
        r["score"] = round(r["total_return_pct"] + r["max_drawdown_pct"] * 0.5 + r["sharpe"] * 5, 2)
    res.sort(key=lambda r: r["score"], reverse=True)
    return {"leaderboard": res, "winner": res[0]["strategy"] if res else None}
