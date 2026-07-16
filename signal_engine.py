"""
ATLAS — Signal Engine
Multi-market: Forex, Stocks, Crypto
Strategies: EMA cross, RSI, MACD, VWAP, Support/Resistance
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
    direction:     str       # BUY | SELL | HOLD
    strength:      str       # STRONG | MODERATE | WEAK
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
def _rsi(s, n=14):
    d = s.diff()
    g = d.clip(lower=0).rolling(n).mean()
    l = (-d.clip(upper=0)).rolling(n).mean()
    return 100 - (100 / (1 + g / l.replace(0, np.nan)))
def _macd(s):
    m = _ema(s,12) - _ema(s,26)
    return m, _ema(m,9)
def _vwap(df):
    tp  = (df["high"]+df["low"]+df["close"])/3
    vol = df["volume"].replace(0,1)
    return (tp*vol).cumsum()/vol.cumsum()
def _atr(df, n=14):
    h,l,c = df["high"],df["low"],df["close"]
    tr = pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    return tr.rolling(n).mean().iloc[-1]


def analyze(df: pd.DataFrame, pair: str) -> Signal:
    cfg  = MARKETS.get(pair.upper(), {})
    label    = cfg.get("label", pair)
    category = cfg.get("category", "Forex")
    pip      = cfg.get("pip", 0.0001)
    sl_pips  = cfg.get("sl_pips", 5) * pip

    now_str = datetime.now(timezone.utc).isoformat()

    if df.empty or len(df) < 50:
        return _hold(pair, label, category, "Not enough data", now_str)

    close = df["close"]
    high  = df["high"]
    low   = df["low"]

    # Indicators
    e9  = _ema(close,9);  e21 = _ema(close,21); e50 = _ema(close,50)
    rsi = _rsi(close,14)
    vwap= _vwap(df)
    mac, macs = _macd(close)
    atr = _atr(df,14)

    # Current values
    c   = float(close.iloc[-1])
    ce9 = float(e9.iloc[-1]);  ce21= float(e21.iloc[-1]); ce50= float(e50.iloc[-1])
    cr  = float(rsi.iloc[-1])
    cv  = float(vwap.iloc[-1])
    cm  = float(mac.iloc[-1]); cms = float(macs.iloc[-1])
    pe9 = float(e9.iloc[-2]);  pe21= float(e21.iloc[-2])
    pm  = float(mac.iloc[-2]); pms = float(macs.iloc[-2])

    supp = float(low.tail(30).min())
    res  = float(high.tail(30).max())

    bull = 0; bear = 0; reasons = []; warnings = []

    # EMA cross
    if pe9<=pe21 and ce9>ce21:
        bull+=35; reasons.append("🟢 EMA 9 crossed above EMA 21 — fresh BUY signal")
    elif pe9>=pe21 and ce9<ce21:
        bear+=35; reasons.append("🔴 EMA 9 crossed below EMA 21 — fresh SELL signal")
    elif ce9>ce21>ce50:
        bull+=15; reasons.append("📈 EMA stacked bullish (9>21>50)")
    elif ce9<ce21<ce50:
        bear+=15; reasons.append("📉 EMA stacked bearish (9<21<50)")

    # RSI
    if cr < 30:
        bull+=25; reasons.append(f"💹 RSI {cr:.1f} — oversold, reversal likely")
    elif cr > 70:
        bear+=25; reasons.append(f"💹 RSI {cr:.1f} — overbought, pullback likely")
    elif cr < 45:
        bear+=8
    elif cr > 55:
        bull+=8
    else:
        warnings.append(f"⚪ RSI {cr:.1f} — neutral zone")

    # VWAP
    if c > cv*1.0002:
        bull+=20; reasons.append(f"📊 Price above VWAP {cv:.4f} — bullish")
    elif c < cv*0.9998:
        bear+=20; reasons.append(f"📊 Price below VWAP {cv:.4f} — bearish")

    # MACD
    if pm<=pms and cm>cms:
        bull+=20; reasons.append("⚡ MACD crossed above signal — momentum turning bullish")
    elif pm>=pms and cm<cms:
        bear+=20; reasons.append("⚡ MACD crossed below signal — momentum turning bearish")
    elif cm>cms: bull+=8
    else:        bear+=8

    # S/R proximity
    near_s = abs(c-supp) < atr*0.5
    near_r = abs(c-res)  < atr*0.5
    if near_s:
        bull+=10; reasons.append(f"🧱 Near support {supp:.4f} — bounce zone")
    elif near_r:
        bear+=10; reasons.append(f"🧱 Near resistance {res:.4f} — rejection zone")

    # Decision
    total = bull+bear or 1
    if bull>bear and bull>=40:
        direction="BUY";  conf=min(int(bull/total*100),95)
        strength="STRONG" if bull>=65 else "MODERATE" if bull>=45 else "WEAK"
    elif bear>bull and bear>=40:
        direction="SELL"; conf=min(int(bear/total*100),95)
        strength="STRONG" if bear>=65 else "MODERATE" if bear>=45 else "WEAK"
    else:
        return _hold(pair,label,category,"No clear signal — conflicting indicators",now_str)

    # Levels
    entry = round(c, 5)
    if direction=="BUY":
        sl  = round(max(entry-sl_pips, supp-pip*3), 5)
        risk= abs(entry-sl)
        tp1 = round(entry+risk,   5)
        tp2 = round(entry+risk*2, 5)
    else:
        sl  = round(min(entry+sl_pips, res+pip*3), 5)
        risk= abs(sl-entry)
        tp1 = round(entry-risk,   5)
        tp2 = round(entry-risk*2, 5)

    sl_p  = round(risk/pip,1)
    tp1_p = round(risk/pip,1)
    rr    = 1.0

    if direction=="BUY":
        action=(f"✅ BUY {label} at {entry:.5f} | "
                f"Stop Loss: {sl:.5f} ({sl_p} pips) | "
                f"TP1: {tp1:.5f} | TP2: {tp2:.5f}")
    else:
        action=(f"🔻 SELL {label} at {entry:.5f} | "
                f"Stop Loss: {sl:.5f} ({sl_p} pips) | "
                f"TP1: {tp1:.5f} | TP2: {tp2:.5f}")

    return Signal(
        pair=pair,label=label,category=category,
        direction=direction,strength=strength,confidence=conf,
        entry=entry,stop_loss=sl,
        take_profit_1=tp1,take_profit_2=tp2,
        sl_pips=sl_p,tp1_pips=tp1_p,rr=rr,
        reasons=reasons,warnings=warnings,
        indicators={
            "rsi":round(cr,1),"ema9":round(ce9,5),
            "ema21":round(ce21,5),"ema50":round(ce50,5),
            "vwap":round(cv,5),"macd":round(cm,6),
            "macd_signal":round(cms,6),"atr":round(atr,5),
            "support":round(supp,5),"resistance":round(res,5),
            "bull_score":bull,"bear_score":bear,
        },
        action=action,
        timestamp=now_str,
    )


def _hold(pair,label,category,reason,ts):
    return Signal(
        pair=pair,label=label,category=category,
        direction="HOLD",strength="WEAK",confidence=0,
        entry=0,stop_loss=0,take_profit_1=0,take_profit_2=0,
        sl_pips=0,tp1_pips=0,rr=0,
        reasons=[f"⏸ {reason}"],
        warnings=["Wait for a clearer setup."],
        indicators={},
        action=f"WAIT — {reason}",
        timestamp=ts,
    )


def scan_all() -> list[dict]:
    """Scan all markets and return signals."""
    results = []
    for pair in MARKETS:
        try:
            df  = fetch_market(pair, "5min")
            sig = analyze(df, pair)
            results.append(asdict(sig))
            print(f"[ATLAS] {pair}: {sig.direction} | {sig.confidence}% | {sig.strength}")
        except Exception as e:
            print(f"[ATLAS] Error on {pair}: {e}")
    return results
