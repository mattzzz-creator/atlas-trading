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


def _get_session_info(as_of=None):
    """Get current session and time info. Pass as_of (naive UTC datetime) to replay history."""
    now = as_of if as_of is not None else datetime.now(timezone.utc).replace(tzinfo=None)
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


def _get_asian_range(df, as_of=None):
    """
    Get Asian session high/low (00:00-07:00 UTC).
    This is the range that London will break out of.
    Pass as_of (naive UTC datetime) to replay history.
    """
    now = as_of if as_of is not None else datetime.now(timezone.utc).replace(tzinfo=None)
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


def analyze_gold(df: pd.DataFrame, as_of=None) -> Signal:
    """London Breakout analysis for Gold. Pass as_of (naive UTC datetime) to replay history."""
    pair     = "XAUUSD"
    label    = "XAU/USD"
    category = "Forex"
    pip      = 0.10   # Gold pip = $0.10

    now_str = (as_of or datetime.now(timezone.utc)).isoformat()

    if df.empty or len(df) < 30:
        return _hold(pair, label, category, "Not enough data", now_str)

    session = _get_session_info(as_of)
    close   = df["close"]
    high    = df["high"]
    low     = df["low"]

    c    = float(close.iloc[-1])
    cr   = float(_rsi(close, 14).iloc[-1])
    atr  = _atr(df, 14)
    trend = _get_h4_trend(df)

    # Get Asian range
    asian_high, asian_low, asian_range = _get_asian_range(df, as_of)

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
        return _hold(pair, label, category,
            f"Asian range too tight ({asian_range_pips:.0f} pips) — high false-breakout risk, skipping", now_str)
    elif asian_range_pips > 100:
        warnings.append(f"⚠️ Asian range very wide ({asian_range_pips:.0f} pips) — reduce size")

    # ── BUY breakout — price breaks above Asian high ──────────
    breakout_buffer = pip * 5  # 5 pip buffer to confirm breakout (was 3 — too easily whipsawed)

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
    # Raised from 50 → 60: a bare breakout (50 pts) can no longer fire alone —
    # it now needs trend OR RSI confirmation too, cutting down whipsaw entries.
    if bull >= 60 and bull > bear:
        direction  = "BUY"
        confidence = min(int(bull / (bull + bear + 1) * 100), 95)
        strength   = "STRONG" if bull >= 80 else "MODERATE"
    elif bear >= 60 and bear > bull:
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


def analyze_scalp(df: pd.DataFrame, as_of=None) -> Signal:
    """
    EMA/RSI momentum scalp for EUR/USD.
    Fast EMA(9)/EMA(21) fresh crossover + RSI(14) momentum confirmation +
    price alignment + London/NY session filter + minimum trend-conviction filter.
    Fixed tight SL (15 pips) sized to fit a small account, RR 1:1.5.
    Designed for frequent small trades — NOT one-per-session like gold.
    """
    pair     = "EURUSD"
    label    = "EUR/USD"
    category = "Forex"
    pip      = 0.0001

    now_str = (as_of or datetime.now(timezone.utc)).isoformat()

    if df.empty or len(df) < 30:
        return _hold(pair, label, category, "Not enough data", now_str)

    now = as_of if as_of is not None else datetime.now(timezone.utc).replace(tzinfo=None)
    hour = now.hour + now.minute / 60

    # ── Requirement 1: active session only (London through NY, ~07:00-16:00 UTC) ──
    if not (7 <= hour < 16):
        return _hold(pair, label, category,
            f"Outside London/NY session ({hour:.1f}h UTC) — spreads too wide / low liquidity", now_str)

    close = df["close"]
    c     = float(close.iloc[-1])

    ema_fast = _ema(close, 9)
    ema_slow = _ema(close, 21)
    rsi      = _rsi(close, 14)

    if pd.isna(ema_slow.iloc[-1]) or pd.isna(rsi.iloc[-1]) or pd.isna(rsi.iloc[-2]):
        return _hold(pair, label, category, "Indicators not ready", now_str)

    ef, es   = float(ema_fast.iloc[-1]), float(ema_slow.iloc[-1])
    ef_p, es_p = float(ema_fast.iloc[-2]), float(ema_slow.iloc[-2])
    cr, cr_prev = float(rsi.iloc[-1]), float(rsi.iloc[-2])
    separation_pips = abs(ef - es) / pip

    crossed_up   = ef_p <= es_p and ef > es
    crossed_down = ef_p >= es_p and ef < es

    # ── Requirement 2: minimum trend conviction — reject flat/choppy EMAs ──
    # A fresh cross is exempt (separation is near-zero right at the cross by
    # definition — that's not the same thing as a flat/choppy market with no cross).
    if separation_pips < 2.5 and not (crossed_up or crossed_down):
        return _hold(pair, label, category,
            f"EMAs too flat ({separation_pips:.1f} pips apart) — no clear trend", now_str)

    reasons, warnings = [], []
    bull = bear = 0

    if crossed_up:
        bull += 40; reasons.append(f"🟢 EMA9 crossed above EMA21 — fresh bullish momentum")
    elif ef > es:
        bull += 15
    if crossed_down:
        bear += 40; reasons.append(f"🔴 EMA9 crossed below EMA21 — fresh bearish momentum")
    elif ef < es:
        bear += 15

    # Tightened: require RSI clearly past the midline (55/45), not just barely over 50 —
    # weak momentum right at 50 was confirming crosses that had no real push behind them.
    if cr > 55 and cr > cr_prev:
        bull += 25; reasons.append(f"📈 RSI {cr:.0f} above 55 and rising — momentum confirms")
    if cr < 45 and cr < cr_prev:
        bear += 25; reasons.append(f"📉 RSI {cr:.0f} below 45 and falling — momentum confirms")

    if c > ef > es:
        bull += 20; reasons.append("✅ Price above both EMAs — trend aligned")
    if c < ef < es:
        bear += 20; reasons.append("✅ Price below both EMAs — trend aligned")

    if separation_pips >= 6:
        bull += 10 if ef > es else 0
        bear += 10 if ef < es else 0

    # ── Decision — needs a fresh cross AND RSI confirmation, not either alone ──
    if bull >= 65 and bull > bear and crossed_up and cr > 55:
        direction, confidence = "BUY", min(bull, 95)
        strength = "STRONG" if bull >= 85 else "MODERATE"
    elif bear >= 65 and bear > bull and crossed_down and cr < 45:
        direction, confidence = "SELL", min(bear, 95)
        strength = "STRONG" if bear >= 85 else "MODERATE"
    else:
        return _hold(pair, label, category,
            "No fresh EMA cross + RSI confirmation together — waiting", now_str)

    # ── Fixed tight levels sized for small accounts ─────────────
    entry   = round(c, 5)
    SL_PIPS = 15
    RR      = 1.5
    sl_dist = pip * SL_PIPS

    if direction == "BUY":
        sl  = round(entry - sl_dist, 5)
        tp1 = round(entry + sl_dist * RR, 5)
        tp2 = round(entry + sl_dist * RR * 1.5, 5)
    else:
        sl  = round(entry + sl_dist, 5)
        tp1 = round(entry - sl_dist * RR, 5)
        tp2 = round(entry - sl_dist * RR * 1.5, 5)

    sl_p  = SL_PIPS
    tp1_p = round(abs(tp1 - entry) / pip, 1)
    rr    = RR

    action = (
        f"{direction} EUR/USD at {entry:.5f} | "
        f"SL: {sl:.5f} ({sl_p} pips) | "
        f"TP1: {tp1:.5f} ({tp1_p} pips) | "
        f"RR: 1:{rr} | "
        f"RSI: {cr:.0f} | EMA sep: {separation_pips:.1f} pips"
    )

    return Signal(
        pair=pair, label=label, category=category,
        direction=direction, strength=strength, confidence=confidence,
        entry=entry, stop_loss=sl,
        take_profit_1=tp1, take_profit_2=tp2,
        sl_pips=sl_p, tp1_pips=tp1_p, rr=rr,
        reasons=reasons[:4], warnings=warnings,
        indicators={
            "rsi": round(cr, 1), "ema_fast": round(ef, 5), "ema_slow": round(es, 5),
            "separation_pips": round(separation_pips, 1),
        },
        action=action,
        timestamp=now_str,
    )


def analyze_meanrev(df: pd.DataFrame, as_of=None) -> Signal:
    """
    Bollinger Band + RSI mean-reversion scalp for EUR/USD.
    Fades price back to the mean after a confirmed reversal from a band
    extreme — the opposite idea from the momentum scalp. Stop sits just
    beyond the actual extreme touched (not a fixed distance), target is
    the mean itself — designed to minimize loss size per trade versus a
    fixed-pip system, since risk scales with how far price actually
    overextended rather than a one-size-fits-all number.
    """
    pair     = "EURUSD"
    label    = "EUR/USD"
    category = "Forex"
    pip      = 0.0001

    now_str = (as_of or datetime.now(timezone.utc)).isoformat()

    if df.empty or len(df) < 25:
        return _hold(pair, label, category, "Not enough data", now_str)

    now = as_of if as_of is not None else datetime.now(timezone.utc).replace(tzinfo=None)
    hour = now.hour + now.minute / 60

    # ── Requirement 1: core London/NY overlap only ──────────────
    # Narrowed from 07:00-16:00 -> 10:00-15:00: backtest showed the broad
    # session edges (07-09h, 14h) underperforming the core overlap hours.
    # This is a hypothesis from a modest sample (5-8 trades/hour) — re-test
    # after this change to confirm it actually helps rather than just
    # shrinking the sample.
    if not (10 <= hour < 15):
        return _hold(pair, label, category,
            f"Outside core overlap session ({hour:.1f}h UTC)", now_str)

    close = df["close"]
    low   = df["low"]
    high  = df["high"]
    c     = float(close.iloc[-1])

    mid, upper, lower = _bollinger(close, 20, 2)
    rsi = _rsi(close, 14)

    if pd.isna(lower.iloc[-2]) or pd.isna(rsi.iloc[-2]):
        return _hold(pair, label, category, "Indicators not ready", now_str)

    band_width_pips = (upper.iloc[-1] - lower.iloc[-1]) / pip

    # ── Requirement 2: real volatility but not a runaway trend ──
    # Floor unchanged (15 pips — reject dead-flat noise). New ceiling (30
    # pips): backtest showed the "wide band" trades winning LESS often
    # (35.3%) than tighter ones (54.5%) — a very wide band likely means
    # price is trending hard, not ranging, so fading it fights the trend.
    if band_width_pips < 15:
        return _hold(pair, label, category,
            f"Bands too narrow ({band_width_pips:.1f} pips) — no real range to fade", now_str)
    if band_width_pips > 30:
        return _hold(pair, label, category,
            f"Bands too wide ({band_width_pips:.1f} pips) — likely trending, not ranging", now_str)

    prev_low, prev_high   = float(low.iloc[-2]), float(high.iloc[-2])
    prev_close            = float(close.iloc[-2])
    prev_lower, prev_upper = float(lower.iloc[-2]), float(upper.iloc[-2])
    cr, cr_prev            = float(rsi.iloc[-1]), float(rsi.iloc[-2])
    mean_price              = float(mid.iloc[-1])

    # Touched below lower band on the PREVIOUS candle, and current close reclaims back inside
    touched_low  = prev_low <= prev_lower
    reclaim_up   = touched_low and c > float(lower.iloc[-1])
    touched_high = prev_high >= prev_upper
    reclaim_down = touched_high and c < float(upper.iloc[-1])

    reasons, warnings = [], []
    bull = bear = 0

    if reclaim_up:
        bull += 50; reasons.append("🟢 Price touched lower band and reclaimed back inside — reversal confirmed")
    if reclaim_down:
        bear += 50; reasons.append("🔴 Price touched upper band and reclaimed back inside — reversal confirmed")

    if cr_prev < 30 and cr > cr_prev:
        bull += 30; reasons.append(f"📈 RSI was oversold ({cr_prev:.0f}) and turning up")
    if cr_prev > 70 and cr < cr_prev:
        bear += 30; reasons.append(f"📉 RSI was overbought ({cr_prev:.0f}) and turning down")

    if bull < 65 and bear < 65:
        return _hold(pair, label, category,
            "No confirmed band-extreme reversal with RSI agreement — waiting", now_str)

    direction  = "BUY" if bull > bear else "SELL"
    confidence = min(max(bull, bear), 95)
    strength   = "STRONG" if confidence >= 85 else "MODERATE"

    entry = round(c, 5)
    BUFFER = pip * 3  # a few pips beyond the actual extreme, not a fixed system-wide stop

    if direction == "BUY":
        sl  = round(prev_low - BUFFER, 5)
        tp1 = round(mean_price, 5)
        tp2 = round(float(upper.iloc[-1]), 5)  # stretch target: opposite band
    else:
        sl  = round(prev_high + BUFFER, 5)
        tp1 = round(mean_price, 5)
        tp2 = round(float(lower.iloc[-1]), 5)

    risk   = abs(entry - sl)
    reward = abs(tp1 - entry)
    rr     = round(reward / risk, 2) if risk > 0 else 0

    # ── Requirement: reject poor reward-to-risk setups — price already too close to the mean ──
    if rr < 1.2:
        return _hold(pair, label, category,
            f"Reward too small vs risk (1:{rr}) — price already near the mean", now_str)

    sl_p  = round(risk / pip, 1)
    tp1_p = round(reward / pip, 1)

    action = (
        f"{direction} EUR/USD at {entry:.5f} | "
        f"SL: {sl:.5f} ({sl_p} pips) | "
        f"TP1 (mean): {tp1:.5f} ({tp1_p} pips) | "
        f"RR: 1:{rr} | RSI: {cr:.0f} | Band width: {band_width_pips:.1f} pips"
    )

    return Signal(
        pair=pair, label=label, category=category,
        direction=direction, strength=strength, confidence=confidence,
        entry=entry, stop_loss=sl,
        take_profit_1=tp1, take_profit_2=tp2,
        sl_pips=sl_p, tp1_pips=tp1_p, rr=rr,
        reasons=reasons[:4], warnings=warnings,
        indicators={
            "rsi": round(cr, 1), "band_mid": round(mean_price, 5),
            "band_width_pips": round(band_width_pips, 1),
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
    if pair.upper() == "EURUSD":
        return analyze_scalp(df)

    # All other pairs — skip for now
    return _hold(pair, label, cat, "Not enabled — only Gold + EUR/USD scalp active", now_str)


def _bollinger(s, n=20, k=2):
    sma = s.rolling(n).mean()
    std = s.rolling(n).std()
    return sma, sma + k*std, sma - k*std  # mid, upper, lower

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
    """Scan Gold (swing) + EUR/USD (scalp)."""
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

    try:
        df  = fetch_market("EURUSD", "5min")
        sig = analyze_scalp(df)
        d   = asdict(sig)
        results.append(d)
        if sig.direction != "HOLD":
            print(f"[ATLAS SCALP] ⚡ {sig.direction} | {sig.confidence}% | {sig.strength} | {sig.action[:60]}")
        else:
            r = sig.reasons[0] if sig.reasons else ""
            print(f"[ATLAS SCALP] ⏸ {r[:80]}")
    except Exception as e:
        print(f"[ATLAS SCALP] Error: {e}")

    # Add HOLD for other pairs so dashboard shows them
    other_pairs = ["GBPJPY","SPX500","NASDAQ","BTCUSDT","ETHUSDT"]
    now_str = datetime.now(timezone.utc).isoformat()
    for pair in other_pairs:
        cfg = MARKETS.get(pair, {})
        results.append(asdict(_hold(pair, cfg.get("label",pair),
            cfg.get("category","Forex"), "Not enabled", now_str)))

    return results
