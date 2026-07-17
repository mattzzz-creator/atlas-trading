"""
ATLAS — High Frequency Scalping Engine
Target: 20-50 signals per day
Strategy: Multi-timeframe momentum + mean reversion
Fast M5 entries, tight SL, quick TP
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from market_data import MARKETS, fetch_market, get_price


@dataclass
class Signal:
    pair:          str
    label:         str
    category:      str
    direction:     str
    strength:      str
    confidence:    int
    entry:         float
    stop_loss:     float
    take_profit_1: float
    take_profit_2: float
    sl_pips:       float
    tp1_pips:      float
    rr:            float
    reasons:       list
    warnings:      list
    indicators:    dict
    action:        str
    timestamp:     str


def _ema(s, n): return s.ewm(span=n, adjust=False).mean()

def _rsi(s, n=7):  # Faster RSI period for scalping
    d = s.diff()
    g = d.clip(lower=0).rolling(n).mean()
    l = (-d.clip(upper=0)).rolling(n).mean()
    rs = g / l.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def _atr(df, n=7):  # Faster ATR for scalping
    h,l,c = df["high"],df["low"],df["close"]
    tr = pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    return tr.rolling(n).mean().iloc[-1]

def _stoch(df, k=5, d=3):  # Fast stochastic for scalping
    low_min  = df["low"].rolling(k).min()
    high_max = df["high"].rolling(k).max()
    k_val = 100*(df["close"]-low_min)/(high_max-low_min).replace(0,np.nan)
    return k_val, k_val.rolling(d).mean()

def _bb(s, n=10, std=2.0):  # Bollinger Bands
    mid  = s.rolling(n).mean()
    band = s.rolling(n).std() * std
    return mid-band, mid, mid+band

def _momentum(s, n=5):  # Price momentum
    return s.diff(n)


def analyze(df: pd.DataFrame, pair: str) -> Signal:
    cfg      = MARKETS.get(pair.upper(), {})
    label    = cfg.get("label", pair)
    category = cfg.get("category", "Forex")
    pip      = cfg.get("pip", 0.0001)
    sl_pips  = cfg.get("sl_pips", 20) * pip

    now_str = datetime.now(timezone.utc).isoformat()

    if df.empty or len(df) < 20:
        return _hold(pair, label, category, "Not enough data", now_str)

    close = df["close"]
    high  = df["high"]
    low   = df["low"]

    # ── Fast Indicators for Scalping ─────────────────────────
    e5   = _ema(close, 5)
    e10  = _ema(close, 10)
    e20  = _ema(close, 20)
    rsi  = _rsi(close, 7)    # Fast 7-period RSI
    stk, std_k = _stoch(df, 5, 3)  # Fast stochastic
    bb_low, bb_mid, bb_high = _bb(close, 10, 2.0)
    mom  = _momentum(close, 3)
    atr  = _atr(df, 7)

    # Current values
    c    = float(close.iloc[-1])
    p1   = float(close.iloc[-2])
    p2   = float(close.iloc[-3])

    ce5  = float(e5.iloc[-1])
    ce10 = float(e10.iloc[-1])
    ce20 = float(e20.iloc[-1])
    pe5  = float(e5.iloc[-2])
    pe10 = float(e10.iloc[-2])

    cr   = float(rsi.iloc[-1])
    pr   = float(rsi.iloc[-2])
    csk  = float(stk.iloc[-1]) if not np.isnan(stk.iloc[-1]) else 50
    psk  = float(stk.iloc[-2]) if not np.isnan(stk.iloc[-2]) else 50

    cbb_low  = float(bb_low.iloc[-1])
    cbb_mid  = float(bb_mid.iloc[-1])
    cbb_high = float(bb_high.iloc[-1])

    cmom = float(mom.iloc[-1])
    pmom = float(mom.iloc[-2])

    bull  = 0
    bear  = 0
    reasons = []

    # ══════════════════════════════════════════════════════════
    # BUY SIGNALS — Buy the dip / Buy breakout
    # ══════════════════════════════════════════════════════════

    # 1. Fast EMA cross BUY (+30)
    if pe5 <= pe10 and ce5 > ce10:
        bull += 30
        reasons.append(f"⚡ EMA5 crossed above EMA10 — fast BUY signal")

    # 2. RSI oversold reversal (+30)
    if cr < 30 and cr > pr:
        bull += 30
        reasons.append(f"🟢 RSI {cr:.0f} oversold turning up — BUY dip")
    elif cr < 40 and cr > pr:
        bull += 15
        reasons.append(f"📊 RSI {cr:.0f} low and rising — momentum turning bullish")

    # 3. Stochastic oversold cross (+25)
    if psk < csk and csk < 25:
        bull += 25
        reasons.append(f"🟢 Stoch {csk:.0f} crossing up from oversold")
    elif psk < csk and csk < 35:
        bull += 12

    # 4. Price touched lower Bollinger Band (+25)
    if c <= cbb_low * 1.001:
        bull += 25
        reasons.append(f"🎯 Price hit lower Bollinger Band — mean reversion BUY")
    elif c < cbb_mid:
        bull += 8

    # 5. Bullish momentum (+15)
    if cmom > 0 and pmom < 0:  # Momentum turned positive
        bull += 15
        reasons.append(f"💚 Momentum turning positive — buyers stepping in")
    elif cmom > 0:
        bull += 8

    # 6. Price above EMA20 — trend (+10)
    if c > ce20:
        bull += 10

    # ══════════════════════════════════════════════════════════
    # SELL SIGNALS — Sell the rally / Sell breakdown
    # ══════════════════════════════════════════════════════════

    # 1. Fast EMA cross SELL (+30)
    if pe5 >= pe10 and ce5 < ce10:
        bear += 30
        reasons.append(f"⚡ EMA5 crossed below EMA10 — fast SELL signal")

    # 2. RSI overbought reversal (+30)
    if cr > 70 and cr < pr:
        bear += 30
        reasons.append(f"🔴 RSI {cr:.0f} overbought turning down — SELL rally")
    elif cr > 60 and cr < pr:
        bear += 15
        reasons.append(f"📊 RSI {cr:.0f} high and falling — momentum turning bearish")

    # 3. Stochastic overbought cross (+25)
    if psk > csk and csk > 75:
        bear += 25
        reasons.append(f"🔴 Stoch {csk:.0f} crossing down from overbought")
    elif psk > csk and csk > 65:
        bear += 12

    # 4. Price touched upper Bollinger Band (+25)
    if c >= cbb_high * 0.999:
        bear += 25
        reasons.append(f"🎯 Price hit upper Bollinger Band — mean reversion SELL")
    elif c > cbb_mid:
        bear += 8

    # 5. Bearish momentum (+15)
    if cmom < 0 and pmom > 0:  # Momentum turned negative
        bear += 15
        reasons.append(f"❤️ Momentum turning negative — sellers stepping in")
    elif cmom < 0:
        bear += 8

    # 6. Price below EMA20 — trend (+10)
    if c < ce20:
        bear += 10

    # ── Decision ─────────────────────────────────────────────
    # Lower threshold = more signals
    MIN_SCORE = 30  # Very low — fires lots of signals

    if bull > bear and bull >= MIN_SCORE:
        direction  = "BUY"
        confidence = min(int(bull / (bull + bear + 1) * 100), 95)
        strength   = "STRONG" if bull >= 70 else "MODERATE" if bull >= 50 else "WEAK"
    elif bear > bull and bear >= MIN_SCORE:
        direction  = "SELL"
        confidence = min(int(bear / (bull + bear + 1) * 100), 95)
        strength   = "STRONG" if bear >= 70 else "MODERATE" if bear >= 50 else "WEAK"
    else:
        return _hold(pair, label, category,
                     f"Neutral — Bull:{bull} Bear:{bear} — waiting for setup", now_str)

    # ── Levels ────────────────────────────────────────────────
    entry = round(c, 5)

    if direction == "BUY":
        sl  = round(entry - sl_pips, 5)
        tp1 = round(entry + sl_pips * 1.5, 5)
        tp2 = round(entry + sl_pips * 3.0, 5)
    else:
        sl  = round(entry + sl_pips, 5)
        tp1 = round(entry - sl_pips * 1.5, 5)
        tp2 = round(entry - sl_pips * 3.0, 5)

    sl_p  = round(abs(entry - sl) / pip, 1)
    tp1_p = round(abs(tp1 - entry) / pip, 1)
    rr    = 1.5

    action = (f"{direction} {label} NOW at {entry:.5f} | "
              f"SL: {sl:.5f} ({sl_p} pips) | "
              f"TP1: {tp1:.5f} ({tp1_p} pips) | "
              f"TP2: {tp2:.5f}")

    # Filter reasons to match direction
    if direction == "BUY":
        final = [r for r in reasons if any(x in r for x in ["⚡","🟢","💚","🎯","📊"])]
    else:
        final = [r for r in reasons if any(x in r for x in ["⚡","🔴","❤️","🎯","📊"])]

    return Signal(
        pair=pair, label=label, category=category,
        direction=direction, strength=strength, confidence=confidence,
        entry=entry, stop_loss=sl,
        take_profit_1=tp1, take_profit_2=tp2,
        sl_pips=sl_p, tp1_pips=tp1_p, rr=rr,
        reasons=final[:4], warnings=[],
        indicators={
            "rsi":        round(cr, 1),
            "stoch":      round(csk, 1),
            "ema5":       round(ce5, 5),
            "ema10":      round(ce10, 5),
            "ema20":      round(ce20, 5),
            "bb_low":     round(cbb_low, 5),
            "bb_mid":     round(cbb_mid, 5),
            "bb_high":    round(cbb_high, 5),
            "momentum":   round(cmom, 5),
            "atr":        round(atr, 5),
            "bull_score": bull,
            "bear_score": bear,
        },
        action=action,
        timestamp=now_str,
    )


def _hold(pair, label, category, reason, ts):
    return Signal(
        pair=pair, label=label, category=category,
        direction="HOLD", strength="WEAK", confidence=0,
        entry=0, stop_loss=0, take_profit_1=0, take_profit_2=0,
        sl_pips=0, tp1_pips=0, rr=0,
        reasons=[f"⏸ {reason}"],
        warnings=[],
        indicators={},
        action=f"WAIT — {reason}",
        timestamp=ts,
    )


def scan_all() -> list[dict]:
    results = []
    for pair in MARKETS:
        try:
            df  = fetch_market(pair, "5min")
            sig = analyze(df, pair)
            d   = asdict(sig)
            results.append(d)
            print(f"[ATLAS] {pair}: {sig.direction} | {sig.confidence}% | {sig.strength}")
        except Exception as e:
            print(f"[ATLAS] Error {pair}: {e}")
    return results
