"""
ATLAS — Chart Analysis Engine
Detects support/resistance levels and candlestick "setups" (patterns that
occur AT a level, e.g. a pin bar right at support) for the live chart.
Runs entirely server-side - the frontend just renders what this returns,
no manual drawing involved.
"""
import pandas as pd
import numpy as np
from market_data import fetch_yfinance

GOLD_TICKER = "GC=F"


def _find_pivots(df: pd.DataFrame, left: int = 3, right: int = 3):
    """Returns lists of (index, price) for confirmed swing highs and lows."""
    highs, lows = [], []
    h, l = df["high"].values, df["low"].values
    n = len(df)
    for i in range(left, n - right):
        window_h = h[i-left:i+right+1]
        window_l = l[i-left:i+right+1]
        if h[i] == window_h.max() and (window_h == h[i]).sum() == 1:
            highs.append((i, h[i]))
        if l[i] == window_l.min() and (window_l == l[i]).sum() == 1:
            lows.append((i, l[i]))
    return highs, lows


def _cluster_levels(points, tolerance):
    """Groups nearby pivot prices into levels, scored by touch count."""
    if not points:
        return []
    prices = sorted(p for _, p in points)
    clusters = []
    current = [prices[0]]
    for p in prices[1:]:
        if p - current[-1] <= tolerance:
            current.append(p)
        else:
            clusters.append(current)
            current = [p]
    clusters.append(current)
    return [{"price": float(np.mean(c)), "touches": len(c)} for c in clusters]


def support_resistance(df: pd.DataFrame, lookback: int = 150, max_levels: int = 4):
    """
    Returns up to `max_levels` support levels (below current price) and
    `max_levels` resistance levels (above current price), ranked by touch
    count (more touches = stronger, more-tested level).
    """
    recent = df.tail(lookback).reset_index(drop=True)
    if len(recent) < 30:
        return [], []

    atr = (recent["high"] - recent["low"]).rolling(14).mean().iloc[-1]
    tolerance = atr * 0.5 if pd.notna(atr) and atr > 0 else recent["close"].iloc[-1] * 0.001

    pivot_highs, pivot_lows = _find_pivots(recent, left=3, right=3)
    high_levels = _cluster_levels(pivot_highs, tolerance)
    low_levels = _cluster_levels(pivot_lows, tolerance)

    current_price = float(recent["close"].iloc[-1])
    all_levels = high_levels + low_levels
    resistance = sorted([lv for lv in all_levels if lv["price"] > current_price],
                         key=lambda x: (-x["touches"], x["price"] - current_price))[:max_levels]
    support = sorted([lv for lv in all_levels if lv["price"] <= current_price],
                      key=lambda x: (-x["touches"], current_price - x["price"]))[:max_levels]
    return support, resistance


def _candle_shape(row, atr):
    body = abs(row["close"] - row["open"])
    rng = row["high"] - row["low"]
    upper = row["high"] - max(row["close"], row["open"])
    lower = min(row["close"], row["open"]) - row["low"]
    return body, rng, upper, lower


def detect_setups(df: pd.DataFrame, support: list, resistance: list,
                   lookback: int = 30, near_tolerance_atr: float = 0.5):
    """
    Scans the most recent `lookback` candles for a pattern occurring AT a
    detected support/resistance level - e.g. a bullish pin bar right at
    support, matching the classic "setup" style (pattern + level together,
    not either alone).
    """
    recent = df.tail(lookback).reset_index(drop=True)
    if len(recent) < 5:
        return []

    atr_series = (df["high"] - df["low"]).rolling(14).mean()
    setups = []
    all_levels = [("support", lv) for lv in support] + [("resistance", lv) for lv in resistance]

    for i in range(1, len(recent)):
        row = recent.iloc[i]
        idx_in_df = len(df) - len(recent) + i
        atr = atr_series.iloc[idx_in_df] if idx_in_df < len(atr_series) else np.nan
        if pd.isna(atr) or atr <= 0:
            continue
        body, rng, upper, lower = _candle_shape(row, atr)
        if rng <= 0:
            continue

        bull_pin = lower >= 2 * (upper + body)
        bear_pin = upper >= 2 * (lower + body)
        bull_engulf = recent.iloc[i-1]["close"] < recent.iloc[i-1]["open"] and row["close"] > row["open"] \
            and row["open"] <= recent.iloc[i-1]["close"] and row["close"] >= recent.iloc[i-1]["open"]
        bear_engulf = recent.iloc[i-1]["close"] > recent.iloc[i-1]["open"] and row["close"] < row["open"] \
            and row["open"] >= recent.iloc[i-1]["close"] and row["close"] <= recent.iloc[i-1]["open"]

        if not (bull_pin or bear_pin or bull_engulf or bear_engulf):
            continue

        near_tol = atr * near_tolerance_atr
        for level_type, lv in all_levels:
            if abs(row["low"] - lv["price"]) <= near_tol or abs(row["high"] - lv["price"]) <= near_tol or \
               abs(row["close"] - lv["price"]) <= near_tol:
                if bull_pin and level_type == "support":
                    setups.append(_mk_setup(row, "Pin Bar at Support", "bullish", lv))
                elif bear_pin and level_type == "resistance":
                    setups.append(_mk_setup(row, "Pin Bar at Resistance", "bearish", lv))
                elif bull_engulf and level_type == "support":
                    setups.append(_mk_setup(row, "Bullish Engulfing at Support", "bullish", lv))
                elif bear_engulf and level_type == "resistance":
                    setups.append(_mk_setup(row, "Bearish Engulfing at Resistance", "bearish", lv))
    return setups


def _mk_setup(row, label, bias, level):
    return {
        "time": int(row["time"].timestamp()),
        "price": float(row["close"]),
        "low": float(row["low"]),
        "high": float(row["high"]),
        "label": label,
        "bias": bias,
        "level_price": level["price"],
        "level_touches": level["touches"],
    }


def get_gold_chart_data(interval: str = "15m", period: str = "5d", lookback: int = 150):
    """Main entry point - returns candles + support/resistance + setups, ready for the frontend."""
    df = fetch_yfinance(GOLD_TICKER, interval, period)
    if df.empty or len(df) < 30:
        return {"candles": [], "support": [], "resistance": [], "setups": [],
                "note": "Not enough data yet"}

    df = df.reset_index(drop=True)
    # market_data.py's fetch_yfinance always returns a "time" column as a
    # pandas datetime (pd.to_datetime(timestamps, unit="s")) - convert to
    # Unix seconds (int) for lightweight-charts, which expects that exact format.

    support, resistance = support_resistance(df, lookback=lookback)
    setups = detect_setups(df, support, resistance)

    candles = [
        {"time": int(r["time"].timestamp()), "open": float(r["open"]), "high": float(r["high"]),
         "low": float(r["low"]), "close": float(r["close"])}
        for _, r in df.tail(lookback).iterrows()
    ]

    return {
        "candles": candles,
        "support": support,
        "resistance": resistance,
        "setups": setups,
        "current_price": float(df["close"].iloc[-1]),
    }
