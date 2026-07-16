"""
ATLAS — Market Data Engine v2
Forex/Stocks: Alpha Vantage (free, no IP restriction)
Crypto: Binance public API (free, no key needed)
"""

import time
import requests
import pandas as pd
import os
from dotenv import load_dotenv

load_dotenv()

AV_KEY  = os.getenv("ALPHA_VANTAGE_KEY", "demo")
AV_URL  = "https://www.alphavantage.co/query"
BN_URL  = "https://api.binance.com/api/v3"

MARKETS = {
    "XAUUSD": {"label":"XAU/USD",  "av_symbol":"XAU",   "av_market":"USD",  "source":"av_fx",     "pip":0.10,  "sl_pips":8,  "category":"Forex"},
    "EURUSD": {"label":"EUR/USD",  "av_symbol":"EUR",   "av_market":"USD",  "source":"av_fx",     "pip":0.0001,"sl_pips":5,  "category":"Forex"},
    "GBPJPY": {"label":"GBP/JPY",  "av_symbol":"GBP",   "av_market":"JPY",  "source":"av_fx",     "pip":0.01,  "sl_pips":8,  "category":"Forex"},
    "SPX500": {"label":"S&P 500",  "av_symbol":"SPY",   "av_market":"",     "source":"av_stock",  "pip":0.10,  "sl_pips":10, "category":"Stocks"},
    "NASDAQ": {"label":"Nasdaq",   "av_symbol":"QQQ",   "av_market":"",     "source":"av_stock",  "pip":0.10,  "sl_pips":15, "category":"Stocks"},
    "BTCUSDT":{"label":"BTC/USDT", "symbol":"BTCUSDT",  "av_market":"",     "source":"binance",   "pip":1.0,   "sl_pips":50, "category":"Crypto"},
    "ETHUSDT":{"label":"ETH/USDT", "symbol":"ETHUSDT",  "av_market":"",     "source":"binance",   "pip":0.10,  "sl_pips":10, "category":"Crypto"},
}

_last_av_call = 0
AV_DELAY = 13.0  # Alpha Vantage free = 5 calls/min = 12s between calls

def _av_get(params):
    global _last_av_call
    elapsed = time.time() - _last_av_call
    if elapsed < AV_DELAY:
        time.sleep(AV_DELAY - elapsed)
    _last_av_call = time.time()
    params["apikey"] = AV_KEY
    try:
        resp = requests.get(AV_URL, params=params, timeout=15)
        return resp.json()
    except Exception as e:
        print(f"[Data] AV error: {e}")
        return {}


def fetch_av_fx(from_sym: str, to_sym: str, interval: str = "5min") -> pd.DataFrame:
    """Fetch forex data from Alpha Vantage."""
    data = _av_get({
        "function":    "FX_INTRADAY",
        "from_symbol": from_sym,
        "to_symbol":   to_sym,
        "interval":    interval,
        "outputsize":  "compact",
    })

    key = f"Time Series FX ({interval})"
    ts  = data.get(key, {})
    if not ts:
        print(f"[Data] No AV FX data for {from_sym}/{to_sym}: {list(data.keys())}")
        return pd.DataFrame()

    rows = []
    for t, v in ts.items():
        rows.append({
            "time":   pd.Timestamp(t),
            "open":   float(v["1. open"]),
            "high":   float(v["2. high"]),
            "low":    float(v["3. low"]),
            "close":  float(v["4. close"]),
            "volume": 1.0,
        })

    df = pd.DataFrame(rows).sort_values("time").reset_index(drop=True)
    return df


def fetch_av_stock(symbol: str, interval: str = "5min") -> pd.DataFrame:
    """Fetch stock/ETF data from Alpha Vantage."""
    data = _av_get({
        "function":   "TIME_SERIES_INTRADAY",
        "symbol":     symbol,
        "interval":   interval,
        "outputsize": "compact",
    })

    key = f"Time Series ({interval})"
    ts  = data.get(key, {})
    if not ts:
        print(f"[Data] No AV stock data for {symbol}: {list(data.keys())}")
        return pd.DataFrame()

    rows = []
    for t, v in ts.items():
        rows.append({
            "time":   pd.Timestamp(t),
            "open":   float(v["1. open"]),
            "high":   float(v["2. high"]),
            "low":    float(v["3. low"]),
            "close":  float(v["4. close"]),
            "volume": float(v["5. volume"]),
        })

    df = pd.DataFrame(rows).sort_values("time").reset_index(drop=True)
    return df


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
        df[["open","high","low","close","volume"]] = df[["open","high","low","close","volume"]].astype(float)
        return df[["time","open","high","low","close","volume"]].sort_values("time").reset_index(drop=True)
    except Exception as e:
        print(f"[Data] Binance error {symbol}: {e}")
        return pd.DataFrame()


def fetch_market(pair: str, timeframe: str = "5min") -> pd.DataFrame:
    """Unified fetch for any market."""
    cfg = MARKETS.get(pair.upper())
    if not cfg:
        return pd.DataFrame()

    src = cfg["source"]

    if src == "av_fx":
        return fetch_av_fx(cfg["av_symbol"], cfg["av_market"], "5min")

    elif src == "av_stock":
        return fetch_av_stock(cfg["av_symbol"], "5min")

    elif src == "binance":
        return fetch_binance(cfg["symbol"], "5m")

    return pd.DataFrame()


def get_price(pair: str) -> float:
    """Get current price for any pair."""
    cfg = MARKETS.get(pair.upper(), {})
    src = cfg.get("source", "")

    if src == "binance":
        try:
            r = requests.get(f"{BN_URL}/ticker/price",
                params={"symbol": cfg["symbol"]}, timeout=5)
            return float(r.json().get("price", 0))
        except:
            return 0.0

    elif src == "av_fx":
        data = _av_get({
            "function":    "CURRENCY_EXCHANGE_RATE",
            "from_currency": cfg["av_symbol"],
            "to_currency":   cfg["av_market"],
        })
        try:
            return float(data["Realtime Currency Exchange Rate"]["5. Exchange Rate"])
        except:
            return 0.0

    elif src == "av_stock":
        data = _av_get({
            "function": "GLOBAL_QUOTE",
            "symbol":   cfg["av_symbol"],
        })
        try:
            return float(data["Global Quote"]["05. price"])
        except:
            return 0.0

    return 0.0
