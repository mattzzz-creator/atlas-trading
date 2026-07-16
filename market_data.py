"""
ATLAS — Market Data Engine v3
Uses yfinance (Yahoo Finance) — completely free, no API key, no rate limits.
Crypto: Binance public API — free, no key needed.
"""

import requests
import pandas as pd
import numpy as np
import os
from datetime import datetime, timedelta

BN_URL = "https://api.binance.com/api/v3"

MARKETS = {
    "XAUUSD": {"label":"XAU/USD",  "yf":"GC=F",    "source":"yfinance", "pip":0.10,  "sl_pips":8,  "category":"Forex"},
    "EURUSD": {"label":"EUR/USD",  "yf":"EURUSD=X", "source":"yfinance", "pip":0.0001,"sl_pips":5,  "category":"Forex"},
    "GBPJPY": {"label":"GBP/JPY",  "yf":"GBPJPY=X", "source":"yfinance", "pip":0.01,  "sl_pips":8,  "category":"Forex"},
    "SPX500": {"label":"S&P 500",  "yf":"^GSPC",    "source":"yfinance", "pip":0.10,  "sl_pips":10, "category":"Stocks"},
    "NASDAQ": {"label":"Nasdaq",   "yf":"^IXIC",    "source":"yfinance", "pip":0.10,  "sl_pips":15, "category":"Stocks"},
    "BTCUSDT":{"label":"BTC/USDT", "symbol":"BTCUSDT","source":"binance", "pip":1.0,   "sl_pips":50, "category":"Crypto"},
    "ETHUSDT":{"label":"ETH/USDT", "symbol":"ETHUSDT","source":"binance", "pip":0.10,  "sl_pips":10, "category":"Crypto"},
}


def fetch_yfinance(ticker: str, interval: str = "5m", period: str = "1d") -> pd.DataFrame:
    """Fetch data from Yahoo Finance — no API key needed."""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        params = {
            "interval": interval,
            "range":    period,
            "includePrePost": "false",
        }
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        data = resp.json()

        result = data.get("chart", {}).get("result", [])
        if not result:
            print(f"[Data] No Yahoo data for {ticker}")
            return pd.DataFrame()

        r         = result[0]
        timestamps= r.get("timestamp", [])
        quotes    = r.get("indicators", {}).get("quote", [{}])[0]

        if not timestamps:
            return pd.DataFrame()

        df = pd.DataFrame({
            "time":   pd.to_datetime(timestamps, unit="s"),
            "open":   quotes.get("open", []),
            "high":   quotes.get("high", []),
            "low":    quotes.get("low", []),
            "close":  quotes.get("close", []),
            "volume": quotes.get("volume", []),
        })

        df = df.dropna(subset=["open","high","low","close"])
        df[["open","high","low","close"]] = df[["open","high","low","close"]].astype(float)
        df["volume"] = df["volume"].fillna(1).astype(float)
        df = df.sort_values("time").reset_index(drop=True)
        print(f"[Data] Yahoo {ticker}: {len(df)} candles")
        return df

    except Exception as e:
        print(f"[Data] Yahoo error {ticker}: {e}")
        return pd.DataFrame()


def fetch_binance(symbol: str, interval: str = "5m", bars: int = 100) -> pd.DataFrame:
    """Fetch crypto from Binance — no key needed."""
    try:
        resp = requests.get(f"{BN_URL}/klines",
            params={"symbol": symbol, "interval": interval, "limit": bars}, timeout=10)
        data = resp.json()
        if not isinstance(data, list):
            return pd.DataFrame()
        df = pd.DataFrame(data, columns=[
            "time","open","high","low","close","volume",
            "close_time","quote_vol","trades","taker_buy_base","taker_buy_quote","ignore"])
        df["time"]  = pd.to_datetime(df["time"], unit="ms")
        df[["open","high","low","close","volume"]] = \
            df[["open","high","low","close","volume"]].astype(float)
        df = df[["time","open","high","low","close","volume"]]\
               .sort_values("time").reset_index(drop=True)
        print(f"[Data] Binance {symbol}: {len(df)} candles")
        return df
    except Exception as e:
        print(f"[Data] Binance error {symbol}: {e}")
        return pd.DataFrame()


def fetch_market(pair: str, timeframe: str = "5min") -> pd.DataFrame:
    """Unified fetch for any market."""
    cfg = MARKETS.get(pair.upper())
    if not cfg:
        return pd.DataFrame()

    if cfg["source"] == "yfinance":
        return fetch_yfinance(cfg["yf"], "1h", "5d")
    elif cfg["source"] == "binance":
        return fetch_binance(cfg["symbol"], "5m")

    return pd.DataFrame()


def get_price(pair: str) -> float:
    """Get latest price for any pair."""
    cfg = MARKETS.get(pair.upper(), {})

    if cfg.get("source") == "binance":
        try:
            r = requests.get(f"{BN_URL}/ticker/price",
                params={"symbol": cfg["symbol"]}, timeout=5)
            return float(r.json().get("price", 0))
        except:
            return 0.0

    elif cfg.get("source") == "yfinance":
        df = fetch_yfinance(cfg["yf"], "1m", "1d")
        if not df.empty:
            return float(df["close"].iloc[-1])

    return 0.0
