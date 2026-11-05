"""Technical analysis: trend, S/R, RSI, MACD, EMA, Bollinger, ATR, Fibonacci, price action, Smart Money Concepts."""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def macd(s: pd.Series, fast=12, slow=26, sig=9):
    m = ema(s, fast) - ema(s, slow)
    signal = ema(m, sig)
    return m, signal, m - signal


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def bollinger(s: pd.Series, n=20, k=2.0):
    mid = s.rolling(n).mean()
    sd = s.rolling(n).std()
    return mid + k * sd, mid, mid - k * sd


def swings(df: pd.DataFrame, left: int = 3, right: int = 3) -> tuple[list, list]:
    highs, lows = [], []
    h, l = df["high"].values, df["low"].values
    for i in range(left, len(df) - right):
        if h[i] == max(h[i - left:i + right + 1]):
            highs.append((i, float(h[i])))
        if l[i] == min(l[i - left:i + right + 1]):
            lows.append((i, float(l[i])))
    return highs, lows


def support_resistance(df: pd.DataFrame, tolerance: float = 0.004, top: int = 4) -> dict:
    highs, lows = swings(df)
    levels = [p for _, p in highs] + [p for _, p in lows]
    clusters: list[list[float]] = []
    for lv in sorted(levels):
        if clusters and abs(lv - np.mean(clusters[-1])) / lv < tolerance:
            clusters[-1].append(lv)
        else:
            clusters.append([lv])
    price = float(df["close"].iloc[-1])
    zones = sorted(({"level": round(float(np.mean(c)), 6), "touches": len(c)} for c in clusters),
                   key=lambda z: z["touches"], reverse=True)
    sup = sorted([z for z in zones if z["level"] < price], key=lambda z: price - z["level"])[:top]
    res = sorted([z for z in zones if z["level"] > price], key=lambda z: z["level"] - price)[:top]
    return {"support": sup, "resistance": res}


def fibonacci(df: pd.DataFrame, lookback: int = 120) -> dict:
    w = df.tail(lookback)
    hi, lo = float(w["high"].max()), float(w["low"].min())
    up = w["high"].idxmax() > w["low"].idxmin()  # last swing direction
    diff = hi - lo
    ratios = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1, 1.272, 1.618]
    lv = {str(r): round(hi - diff * r, 6) if up else round(lo + diff * r, 6) for r in ratios}
    return {"swing_high": hi, "swing_low": lo, "direction": "up" if up else "down", "levels": lv}


def smc(df: pd.DataFrame) -> dict:
    """Smart Money Concepts: market structure (BOS/CHoCH), order blocks, fair value gaps, liquidity."""
    highs, lows = swings(df, 3, 3)
    events = []
    trend = None
    last_h = last_l = None
    hi_i = lo_i = 0
    closes = df["close"].values
    for i in range(len(df)):
        while hi_i < len(highs) and highs[hi_i][0] + 3 <= i:
            last_h = highs[hi_i]; hi_i += 1
        while lo_i < len(lows) and lows[lo_i][0] + 3 <= i:
            last_l = lows[lo_i]; lo_i += 1
        if last_h and closes[i] > last_h[1]:
            events.append({"i": i, "type": "BOS" if trend == "bull" else "CHoCH", "dir": "bull", "level": last_h[1]})
            trend, last_h = "bull", None
        elif last_l and closes[i] < last_l[1]:
            events.append({"i": i, "type": "BOS" if trend == "bear" else "CHoCH", "dir": "bear", "level": last_l[1]})
            trend, last_l = "bear", None
    # Order blocks: last opposite candle before the impulsive move that caused the structure break
    obs = []
    o, c, h, l = df["open"].values, df["close"].values, df["high"].values, df["low"].values
    for ev in events[-6:]:
        rng = range(ev["i"] - 1, max(ev["i"] - 15, 0), -1)
        for j in rng:
            if ev["dir"] == "bull" and c[j] < o[j]:
                obs.append({"type": "bullish OB", "high": float(h[j]), "low": float(l[j]),
                            "time": str(df["time"].iloc[j])}); break
            if ev["dir"] == "bear" and c[j] > o[j]:
                obs.append({"type": "bearish OB", "high": float(h[j]), "low": float(l[j]),
                            "time": str(df["time"].iloc[j])}); break
    fvgs = []
    for j in range(2, len(df)):
        if l[j] > h[j - 2]:
            fvgs.append({"type": "bullish FVG", "top": float(l[j]), "bottom": float(h[j - 2]), "i": j})
        elif h[j] < l[j - 2]:
            fvgs.append({"type": "bearish FVG", "top": float(l[j - 2]), "bottom": float(h[j]), "i": j})
    price = float(c[-1])
    open_fvgs = [f for f in fvgs[-40:] if not (f["bottom"] <= price <= f["top"])][-5:]
    eq_highs = _equal(highs[-12:]); eq_lows = _equal(lows[-12:])
    return {"structure": trend or "range",
            "last_events": [{**e, "time": str(df["time"].iloc[e["i"]])} for e in events[-5:]],
            "order_blocks": obs[-4:], "fair_value_gaps": open_fvgs,
            "liquidity": {"equal_highs": eq_highs, "equal_lows": eq_lows}}


def _equal(points, tol=0.0015):
    out = []
    for a in range(len(points)):
        for b in range(a + 1, len(points)):
            if abs(points[a][1] - points[b][1]) / points[a][1] < tol:
                out.append(round((points[a][1] + points[b][1]) / 2, 6))
    return sorted(set(out))[-4:]


def candle_patterns(df: pd.DataFrame) -> list[str]:
    o, h, l, c = (df[k].values for k in ("open", "high", "low", "close"))
    pats = []
    i = len(df) - 1
    body = abs(c[i] - o[i]); rng = h[i] - l[i] or 1e-9
    upper = h[i] - max(c[i], o[i]); lower = min(c[i], o[i]) - l[i]
    if body / rng < 0.1:
        pats.append("Doji (noaniqlik)")
    if lower > 2 * body and upper < body:
        pats.append("Hammer / Pin bar (pastdan rad etish)")
    if upper > 2 * body and lower < body:
        pats.append("Shooting star (yuqoridan rad etish)")
    if c[i] > o[i] and c[i - 1] < o[i - 1] and c[i] >= o[i - 1] and o[i] <= c[i - 1]:
        pats.append("Bullish engulfing")
    if c[i] < o[i] and c[i - 1] > o[i - 1] and c[i] <= o[i - 1] and o[i] >= c[i - 1]:
        pats.append("Bearish engulfing")
    if h[i] < h[i - 1] and l[i] > l[i - 1]:
        pats.append("Inside bar (siqilish)")
    return pats


def full_analysis(df: pd.DataFrame) -> dict:
    close = df["close"]
    e20, e50, e200 = ema(close, 20), ema(close, 50), ema(close, 200)
    r = rsi(close)
    m, sig, hist = macd(close)
    a = atr(df)
    bu, bm, bl = bollinger(close)
    price = float(close.iloc[-1])
    score = 0
    reasons = []
    if price > e50.iloc[-1]: score += 1; reasons.append("narx EMA50 ustida")
    else: score -= 1; reasons.append("narx EMA50 ostida")
    if len(df) >= 200:
        if e50.iloc[-1] > e200.iloc[-1]: score += 1; reasons.append("EMA50 > EMA200 (uzoq muddatli ko'tarilish)")
        else: score -= 1; reasons.append("EMA50 < EMA200 (uzoq muddatli pasayish)")
    if hist.iloc[-1] > 0: score += 1; reasons.append("MACD gistogramma musbat")
    else: score -= 1; reasons.append("MACD gistogramma manfiy")
    rv = float(r.iloc[-1])
    if rv > 70: reasons.append("RSI haddan tashqari sotib olingan (>70)"); score -= 0.5
    elif rv < 30: reasons.append("RSI haddan tashqari sotilgan (<30)"); score += 0.5
    s = smc(df)
    if s["structure"] == "bull": score += 1
    elif s["structure"] == "bear": score -= 1
    bias = "bullish (ko'tarilish)" if score >= 1.5 else "bearish (pasayish)" if score <= -1.5 else "neytral / range"
    confidence = min(90, int(40 + abs(score) * 10))
    change = lambda n: round((price / float(close.iloc[-n - 1]) - 1) * 100, 2) if len(close) > n else None
    return {
        "symbol": df.attrs.get("symbol"), "price": price, "time": str(df["time"].iloc[-1]),
        "change_pct": {"1": change(1), "24": change(24), "100": change(100)},
        "trend": {"bias": bias, "score": score, "reasons": reasons, "confidence_pct": confidence},
        "indicators": {"ema20": round(float(e20.iloc[-1]), 6), "ema50": round(float(e50.iloc[-1]), 6),
                       "ema200": round(float(e200.iloc[-1]), 6) if len(df) >= 200 else None,
                       "rsi14": round(rv, 2), "macd": round(float(m.iloc[-1]), 6),
                       "macd_signal": round(float(sig.iloc[-1]), 6), "macd_hist": round(float(hist.iloc[-1]), 6),
                       "atr14": round(float(a.iloc[-1]), 6),
                       "bollinger": {"upper": round(float(bu.iloc[-1]), 6), "mid": round(float(bm.iloc[-1]), 6),
                                     "lower": round(float(bl.iloc[-1]), 6)}},
        "levels": support_resistance(df), "fibonacci": fibonacci(df), "smart_money": s,
        "candle_patterns": candle_patterns(df),
        "volatility_pct": round(float(a.iloc[-1]) / price * 100, 3),
        "disclaimer": "Bu tahlil ta'limiy maqsadda; moliyaviy maslahat emas. Risklarni o'zingiz boshqaring.",
    }
