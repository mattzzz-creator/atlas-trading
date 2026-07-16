"""
ATLAS — Market Data Engine
Supports: Forex, Stocks (Indices), Crypto
Forex + Stocks: Twelve Data API (free)
Crypto: Binance public API (no key needed)
"""

import time
import requests
import pandas as pd
import os
from dotenv import load_dotenv

load_dotenv()

API_KEY  = os.getenv("TWELVE_DATA_API_KEY", "demo")
TD_URL   = "https://api.twelvedata.com"
BN_URL   = "https://api.binance.com/api/v3"

# ─── Market definitions ───────────────────────────────────
MARKETS = {
    # Forex
    "XAUUSD": {"label":"XAU/USD",  "symbol":"XAU/USD",  "source":"twelvedata", "pip":0.10,  "sl_pips":8,  "category":"Forex"},
    "EURUSD": {"label":"EUR/USD",  "symbol":"EUR/USD",  "source":"twelvedata", "pip":0.0001,"sl_pips":5,  "category":"Forex"},
    "GBPJPY": {"label":"GBP/JPY",  "symbol":"GBP/JPY",  "source":"twelvedata", "pip":0.01,  "sl_pips":8,  "category":"Forex"},
    # Stocks/Indices
    "SPX500": {"label":"S&P 500",  "symbol":"SPX",       "source":"twelvedata", "pip":0.10,  "sl_pips":10, "category":"Stocks"},
    "NASDAQ": {"label":"Nasdaq",   "symbol":"NDX",       "source":"twelvedata", "pip":0.10,  "sl_pips":15, "category":"Stocks"},
    # Crypto
    "BTCUSDT":{"label":"BTC/USDT", "symbol":"BTCUSDT",  "source":"binance",    "pip":1.0,   "sl_pips":50, "category":"Crypto"},
    "ETHUSDT":{"label":"ETH/USDT", "symbol":"ETHUSDT",  "source":"binance",    "pip":0.10,  "sl_pips":10, "category":"Crypto"},
}

_last_td_call = 0
TD_DELAY = 8.0

def _td_get(params):
    global _last_td_call
    elapsed = time.time() - _last_td_call
    if elapsed < TD_DELAY:
        time.sleep(TD_DELAY - elapsed)
    _last_td_call = time.time()
    return requests.get(f"{TD_URL}/time_series", params=params, timeout=15)


def fetch_candles_td(symbol: str, interval: str = "5min", bars: int = 100) -> pd.DataFrame:
    """Fetch from Twelve Data."""
    params = {"symbol":symbol,"interval":interval,"outputsize":bars,
               "apikey":API_KEY,"format":"JSON"}
    try:
        resp = _td_get(params)
        data = resp.json()
        if data.get("status") == "error":
            print(f"[Data] TD error for {symbol}: {data.get('message')}")
            return pd.DataFrame()
        values = data.get("values", [])
        if not values: return pd.DataFrame()
        df = pd.DataFrame(values)
        df.rename(columns={"datetime":"time"}, inplace=True)
        df["time"] = pd.to_datetime(df["time"])
        df[["open","high","low","close"]] = df[["open","high","low","close"]].astype(float)
        df["volume"] = df.get("volume", pd.Series([1]*len(df))).fillna(1).astype(float)
        return df.sort_values("time").reset_index(drop=True)
    except Exception as e:
        print(f"[Data] TD fetch error {symbol}: {e}")
        return pd.DataFrame()


def fetch_candles_binance(symbol: str, interval: str = "5m", bars: int = 100) -> pd.DataFrame:
    """Fetch from Binance public API — no key needed."""
    try:
        resp = requests.get(f"{BN_URL}/klines",
            params={"symbol":symbol,"interval":interval,"limit":bars}, timeout=10)
        data = resp.json()
        if not isinstance(data, list): return pd.DataFrame()
        df = pd.DataFrame(data, columns=[
            "time","open","high","low","close","volume",
            "close_time","quote_vol","trades","taker_buy_base",
            "taker_buy_quote","ignore"])
        df["time"]  = pd.to_datetime(df["time"], unit="ms")
        df[["open","high","low","close","volume"]] = df[["open","high","low","close","volume"]].astype(float)
        return df[["time","open","high","low","close","volume"]].sort_values("time").reset_index(drop=True)
    except Exception as e:
        print(f"[Data] Binance fetch error {symbol}: {e}")
        return pd.DataFrame()


def fetch_market(pair: str, timeframe: str = "5min") -> pd.DataFrame:
    """Unified fetch for any market."""
    cfg = MARKETS.get(pair.upper())
    if not cfg:
        return pd.DataFrame()
    if cfg["source"] == "binance":
        # Convert timeframe format
        tf_map = {"1min":"1m","5min":"5m","15min":"15m","1h":"1h","4h":"4h","1day":"1d"}
        return fetch_candles_binance(cfg["symbol"], tf_map.get(timeframe,"5m"))
    else:
        return fetch_candles_td(cfg["symbol"], timeframe)


def get_price_binance(symbol: str) -> float:
    try:
        r = requests.get(f"{BN_URL}/ticker/price", params={"symbol":symbol}, timeout=5)
        return float(r.json().get("price", 0))
    except:
        return 0.0


def get_price_td(symbol: str) -> float:
    try:
        r = requests.get(f"{TD_URL}/price",
            params={"symbol":symbol,"apikey":API_KEY}, timeout=5)
        return float(r.json().get("price", 0))
    except:
        return 0.0


def get_price(pair: str) -> float:
    cfg = MARKETS.get(pair.upper(), {})
    if cfg.get("source") == "binance":
        return get_price_binance(cfg["symbol"])
    return get_price_td(cfg.get("symbol", pair))
