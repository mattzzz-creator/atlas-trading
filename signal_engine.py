"""
ATLAS — Gold London Breakout Engine
Pair: XAU/USD only
Session: London Open (07:00-10:00 UTC) = 3PM-6PM Manila
Strategy: Asian Range Breakout + H4 Trend Filter
Target: 1-2 high quality trades per day
RR: 1:3 minimum
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from market_data import MARKETS, fetch_market


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

def _rsi(s, n=14):
    d = s.diff()
    g = d.clip(lower=0).rolling(n).mean()
    l = (-d.clip(upper=0)).rolling(n).mean()
    rs = g / l.replace(0, np.nan)
    return 100 - (100/(1+rs))

def _atr(df, n=14):
    h,l,c = df["high"], df["low"], df["close"]
    tr = pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    return tr.rolling(n).mean().iloc[-1]


def _get_session_info():
    """Get current session and time info."""
    now = datetime.now(timezone.utc)
    h   = now.hour + now.minute / 60

    # Sessions in UTC
    asian_start  = 0.0    # 12AM UTC = 8AM Manila
    asian_end    = 7.0    # 7AM UTC  = 3PM Manila
    london_start = 7.0    # 7AM UTC  = 3PM Manila
    london_end   = 10.0   # 10AM UTC = 6PM Manila
    ny_start     = 12.0   # 12PM UTC = 8PM Manila
    ny_end       = 17.0   # 5PM UTC  = 1AM Manila

    in_asian  = asian_start <= h < asian_end
    in_london = london_start <= h < london_end
    in_ny     = ny_start <= h < ny_end

    # Manila time = UTC + 8
    manila_h = (now.hour + 8) % 24
    manila_time = f"{manila_h:02d}:{now.minute:02d} PHT"

    return {
        "utc_hour":    h,
        "manila_time": manila_time,
        "in_asian":    in_asian,
        "in_london":   in_london,
        "in_ny":       in_ny,
        "session":     "London" if in_london else "New York" if in_ny else "Asian" if in_asian else "Off-Hours",
    }


def _get_asian_range(df):
    """
    Get Asian session high/low (00:00-07:00 UTC).
    This is the range that London will break out of.
    """
    now = datetime.now(timezone.utc)
    # Today's Asian session: midnight to 7AM UTC
    asian_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    asian_end   = now.replace(hour=7, minute=0, second=0, microsecond=0)

    # Filter candles in Asian session
    asian_df = df[
        (df["time"] >= asian_start) &
        (df["time"] < asian_end)
    ]

    if len(asian_df) < 3:
        # Fallback — use last 8 hours of data
        cutoff = now - timedelta(hours=8)
        asian_df = df[df["time"] >= cutoff]

    if asian_df.empty:
        return None, None, None

    asian_high = float(asian_df["high"].max())
    asian_low  = float(asian_df["low"].min())
    asian_range = asian_high - asian_low

    return asian_high, asian_low, asian_range


def _get_h4_trend(df):
    """Determine H4 trend from H1 data."""
    if len(df) < 40:
        return "NEUTRAL"
    close = df["close"]
    e20 = _ema(close, 20)
    e50 = _ema(close, 50)
    c    = float(close.iloc[-1])
    ce20 = float(e20.iloc[-1])
    ce50 = float(e50.iloc[-1])
    if c > ce20 > ce50:
        return "BULLISH"
    elif c < ce20 < ce50:
        return "BEARISH"
    return "NEUTRAL"


def analyze_gold(df: pd.DataFrame) -> Signal:
    """London Breakout analysis for Gold."""
    pair     = "XAUUSD"
    label    = "XAU/USD"
    category = "Forex"
    pip      = 0.10   # Gold pip = $0.10

    now_str = datetime.now(timezone.utc).isoformat()

    if df.empty or len(df) < 30:
        return _hold(pair, label, category, "Not enough data", now_str)

    session = _get_session_info()
    close   = df["close"]
    high    = df["high"]
    low     = df["low"]

    c    = float(close.iloc[-1])
    cr   = float(_rsi(close, 14).iloc[-1])
    atr  = _atr(df, 14)
    trend = _get_h4_trend(df)

    # Get Asian range
    asian_high, asian_low, asian_range = _get_asian_range(df)

    # ── Not London session — show setup info ─────────────────
    if not session["in_london"] and not session["in_ny"]:
        if session["in_asian"] and asian_high and asian_low:
            return _hold(pair, label, category,
                f"Asian session building range | High: {asian_high:.2f} | Low: {asian_low:.2f} | "
                f"Range: {asian_range/pip:.0f} pips | London breakout at 3PM Manila", now_str)
        return _hold(pair, label, category,
            f"Waiting for London open (3PM Manila) | Current: {session['manila_time']}", now_str)

    # ── London/NY session — check for breakout ────────────────
    reasons  = []
    warnings = []
    bull = 0
    bear = 0

    if asian_high is None or asian_low is None:
        return _hold(pair, label, category,
            "Cannot determine Asian range — not enough data", now_str)

    asian_range_pips = asian_range / pip

    # Validate range size — not too tight, not too wide
    if asian_range_pips < 15:
        warnings.append(f"⚠️ Asian range very tight ({asian_range_pips:.0f} pips) — false breakout risk")
    elif asian_range_pips > 100:
        warnings.append(f"⚠️ Asian range very wide ({asian_range_pips:.0f} pips) — reduce size")

    # ── BUY breakout — price breaks above Asian high ──────────
    breakout_buffer = pip * 3  # 3 pip buffer to confirm breakout

    if c > asian_high + breakout_buffer:
        bull += 50
        reasons.append(f"🚀 Price BROKE ABOVE Asian high {asian_high:.2f} — London BUY breakout!")

        # Trend confirmation
        if trend == "BULLISH":
            bull += 30
            reasons.append(f"📈 H4 trend BULLISH — breakout with the trend (high probability)")
        elif trend == "NEUTRAL":
            bull += 10
            warnings.append("⚠️ H4 trend neutral — breakout less reliable")
        else:
            warnings.append("⚠️ H4 trend bearish — counter-trend breakout, be cautious")

        # RSI confirmation
        if 50 < cr < 75:
            bull += 20
            reasons.append(f"💹 RSI {cr:.0f} — momentum supporting the breakout")
        elif cr >= 75:
            warnings.append(f"⚠️ RSI {cr:.0f} overbought — consider waiting for pullback")

    # ── SELL breakout — price breaks below Asian low ──────────
    elif c < asian_low - breakout_buffer:
        bear += 50
        reasons.append(f"💥 Price BROKE BELOW Asian low {asian_low:.2f} — London SELL breakout!")

        if trend == "BEARISH":
            bear += 30
            reasons.append(f"📉 H4 trend BEARISH — breakout with the trend (high probability)")
        elif trend == "NEUTRAL":
            bear += 10
            warnings.append("⚠️ H4 trend neutral — breakout less reliable")
        else:
            warnings.append("⚠️ H4 trend bullish — counter-trend breakout, be cautious")

        if 25 < cr < 50:
            bear += 20
            reasons.append(f"💹 RSI {cr:.0f} — momentum supporting the breakout")
        elif cr <= 25:
            warnings.append(f"⚠️ RSI {cr:.0f} oversold — consider waiting for pullback")

    # ── Price inside range — wait ─────────────────────────────
    else:
        dist_to_high = (asian_high - c) / pip
        dist_to_low  = (c - asian_low) / pip
        return _hold(pair, label, category,
            f"Price inside Asian range | "
            f"{dist_to_high:.0f} pips to HIGH ({asian_high:.2f}) | "
            f"{dist_to_low:.0f} pips to LOW ({asian_low:.2f}) | "
            f"Wait for breakout", now_str)

    # ── Decision ─────────────────────────────────────────────
    if bull >= 50 and bull > bear:
        direction  = "BUY"
        confidence = min(int(bull / (bull + bear + 1) * 100), 95)
        strength   = "STRONG" if bull >= 80 else "MODERATE"
    elif bear >= 50 and bear > bull:
        direction  = "SELL"
        confidence = min(int(bear / (bull + bear + 1) * 100), 95)
        strength   = "STRONG" if bear >= 80 else "MODERATE"
    else:
        return _hold(pair, label, category, "Weak breakout — wait for confirmation", now_str)

    # ── Levels — 1:3 RR ──────────────────────────────────────
    entry   = round(c, 2)
    sl_dist = pip * 12   # 12 pip SL

    if direction == "BUY":
        sl  = round(asian_low - pip * 5, 2)   # SL below Asian low
        sl  = min(sl, entry - sl_dist)         # At least 12 pips
        risk = abs(entry - sl)
        tp1 = round(entry + risk * 2, 2)       # 1:2
        tp2 = round(entry + risk * 3, 2)       # 1:3
    else:
        sl  = round(asian_high + pip * 5, 2)   # SL above Asian high
        sl  = max(sl, entry + sl_dist)          # At least 12 pips
        risk = abs(sl - entry)
        tp1 = round(entry - risk * 2, 2)       # 1:2
        tp2 = round(entry - risk * 3, 2)       # 1:3

    sl_p  = round(abs(entry - sl) / pip, 1)
    tp1_p = round(abs(tp1 - entry) / pip, 1)
    rr    = round(abs(tp1 - entry) / abs(entry - sl), 1)

    action = (
        f"{direction} GOLD at {entry:.2f} | "
        f"SL: {sl:.2f} ({sl_p} pips) | "
        f"TP1: {tp1:.2f} ({tp1_p} pips) | "
        f"TP2: {tp2:.2f} | "
        f"RR: 1:{rr} | "
        f"Asian range: {asian_range_pips:.0f} pips | "
        f"Trend: {trend}"
    )

    return Signal(
        pair=pair, label=label, category=category,
        direction=direction, strength=strength, confidence=confidence,
        entry=entry, stop_loss=sl,
        take_profit_1=tp1, take_profit_2=tp2,
        sl_pips=sl_p, tp1_pips=tp1_p, rr=rr,
        reasons=reasons[:4], warnings=warnings,
        indicators={
            "rsi":          round(cr, 1),
            "trend":        trend,
            "session":      session["session"],
            "manila_time":  session["manila_time"],
            "asian_high":   round(asian_high, 2),
            "asian_low":    round(asian_low, 2),
            "asian_range":  round(asian_range_pips, 1),
            "atr":          round(atr, 2),
            "bull_score":   bull,
            "bear_score":   bear,
        },
        action=action,
        timestamp=now_str,
    )


def analyze(df: pd.DataFrame, pair: str) -> Signal:
    """Route all pairs — only Gold gets full analysis."""
    now_str = datetime.now(timezone.utc).isoformat()
    cfg     = MARKETS.get(pair.upper(), {})
    label   = cfg.get("label", pair)
    cat     = cfg.get("category", "Forex")

    if pair.upper() == "XAUUSD":
        return analyze_gold(df)

    # All other pairs — skip for now
    return _hold(pair, label, cat, "Gold-only mode — other pairs disabled", now_str)


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
    """Only scan Gold."""
    results = []
    try:
        df  = fetch_market("XAUUSD", "5min")
        sig = analyze_gold(df)
        d   = asdict(sig)
        results.append(d)
        if sig.direction != "HOLD":
            print(f"[ATLAS GOLD] ⚡ {sig.direction} | {sig.confidence}% | {sig.strength} | {sig.action[:60]}")
        else:
            r = sig.reasons[0] if sig.reasons else ""
            print(f"[ATLAS GOLD] ⏸ {r[:80]}")
    except Exception as e:
        print(f"[ATLAS GOLD] Error: {e}")

    # Add HOLD for other pairs so dashboard shows them
    other_pairs = ["EURUSD","GBPJPY","SPX500","NASDAQ","BTCUSDT","ETHUSDT"]
    now_str = datetime.now(timezone.utc).isoformat()
    for pair in other_pairs:
        cfg = MARKETS.get(pair, {})
        results.append(asdict(_hold(pair, cfg.get("label",pair),
            cfg.get("category","Forex"), "Gold-only mode", now_str)))

    return results
