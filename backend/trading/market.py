"""Market data for all markets: Crypto (Binance), Stocks / Forex / Indices / Commodities (Yahoo Finance chart API)."""
from __future__ import annotations

import httpx
import pandas as pd

# Public market-data mirrors first (api.binance.com is blocked in some regions)
BINANCE_HOSTS = ["https://data-api.binance.vision", "https://api.binance.com", "https://api1.binance.com",
                 "https://api-gcp.binance.com"]
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/"
UA = {"User-Agent": "Mozilla/5.0 (ROBIN market data)"}

INTERVALS_YH = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "60m", "4h": "60m", "1d": "1d",
                "1w": "1wk", "1M": "1mo"}
RANGE_YH = {"1m": "5d", "5m": "1mo", "15m": "1mo", "30m": "1mo", "1h": "6mo", "4h": "1y", "1d": "5y",
            "1w": "10y", "1M": "max"}

ALIASES = {  # friendly names → yahoo symbols
    "GOLD": "GC=F", "XAUUSD": "GC=F", "OLTIN": "GC=F", "SILVER": "SI=F", "XAGUSD": "SI=F", "OIL": "CL=F",
    "NEFT": "CL=F", "SPX": "^GSPC", "SP500": "^GSPC", "NASDAQ": "^IXIC", "NAS100": "^NDX", "DOW": "^DJI",
    "DAX": "^GDAXI", "DXY": "DX-Y.NYB", "VIX": "^VIX",
}


def classify(symbol: str) -> tuple[str, str]:
    s = symbol.upper().replace("/", "").replace("-", "").strip()
    if s in ALIASES:
        return "yahoo", ALIASES[s]
    if s.endswith(("USDT", "BUSD", "USDC", "FDUSD")) or s.endswith("BTC") and len(s) > 5:
        return "binance", s
    if len(s) == 6 and s.isalpha() and s[3:] in ("USD", "EUR", "GBP", "JPY", "CHF", "AUD", "CAD", "NZD", "RUB", "TRY") \
            and s[:3] in ("USD", "EUR", "GBP", "JPY", "CHF", "AUD", "CAD", "NZD", "XAU", "XAG"):
        return "yahoo", f"{s}=X"
    if s in ("BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "TON", "AVAX", "TRX", "DOT", "LINK"):
        return "binance", s + "USDT"
    return "yahoo", symbol.upper()


async def _binance_get(c: httpx.AsyncClient, path: str, params: dict):
    last: Exception | None = None
    for host in BINANCE_HOSTS:
        try:
            r = await c.get(host + path, params=params)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as e:
            last = e
    raise last or RuntimeError("Binance mavjud emas")


def _yahoo_crypto(sym: str) -> str:
    for q in ("USDT", "USDC", "FDUSD", "BUSD"):
        if sym.endswith(q):
            return f"{sym[:-len(q)]}-USD"
    return sym


async def candles(symbol: str, interval: str = "1h", limit: int = 500) -> pd.DataFrame:
    src, sym = classify(symbol)
    async with httpx.AsyncClient(timeout=30, headers=UA) as c:
        rows = None
        if src == "binance":
            try:
                rows = await _binance_get(c, "/api/v3/klines", {"symbol": sym, "interval": interval,
                                                                "limit": min(limit, 1000)})
            except Exception:
                src, sym = "yahoo", _yahoo_crypto(sym)  # fallback: Yahoo crypto quotes
        if rows is not None:
            df = pd.DataFrame(rows, columns=["t", "open", "high", "low", "close", "volume", "ct", "qv", "n", "tb",
                                             "tq", "x"])
            df["time"] = pd.to_datetime(df["t"], unit="ms", utc=True)
        else:
            r = await c.get(YAHOO + sym, params={"interval": INTERVALS_YH.get(interval, "1d"),
                                                 "range": RANGE_YH.get(interval, "1y")})
            r.raise_for_status()
            res = r.json()["chart"]["result"][0]
            q = res["indicators"]["quote"][0]
            df = pd.DataFrame({"time": pd.to_datetime(res["timestamp"], unit="s", utc=True), "open": q["open"],
                               "high": q["high"], "low": q["low"], "close": q["close"], "volume": q["volume"]})
            if interval == "4h":
                df = df.set_index("time").resample("4h").agg({"open": "first", "high": "max", "low": "min",
                                                              "close": "last", "volume": "sum"}).reset_index()
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["close"]).reset_index(drop=True)
    df.attrs["symbol"], df.attrs["source"] = sym, src
    return df[["time", "open", "high", "low", "close", "volume"]].tail(limit).reset_index(drop=True)


async def price(symbol: str) -> float:
    src, sym = classify(symbol)
    if src == "binance":
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                return float((await _binance_get(c, "/api/v3/ticker/price", {"symbol": sym}))["price"])
        except Exception:
            symbol = _yahoo_crypto(sym)
    df = await candles(symbol, "1d", 5)
    return float(df["close"].iloc[-1])
