"""
ATLAS — Gold Manual Trading Guide Engine (Multi-Timeframe)
Python port of the TradingView "Gold Manual Trading Guide" Pine indicator,
now computing FOUR INDEPENDENT signals - one per timeframe (M5, M15, H1,
D1) - since confluence genuinely differs by timeframe, not just what's
displayed. Each gets its own pair key (XAUUSD-GUIDE-M5 etc.) so they show
up as separate cards/entries and can drive separate chart panels.

Runs on ATLAS's existing scan schedule (every 3 min) and reuses the
existing Signal dataclass + Telegram pipeline - no TradingView webhook,
no paid plan needed.

DATA NOTES (real limitations, not identical to what was backtested):
- Gold price = Yahoo Finance gold futures (GC=F), not XM's GOLD# CFD.
  Close, but not the exact instrument the MT5 backtests used.
- DXY approximated via Yahoo ticker DX-Y.NYB.
- The tier win rates below came from MT5 GOLD# tick-level backtesting on
  M1/M5 specifically, not this multi-timeframe version or this data
  source - same LOGIC at M5, but the H1/D1 profiles have NOT been
  separately backtested. Treat H1/D1 signals as informational only until
  they've been validated the same rigorous way M5 was.
"""
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from market_data import fetch_yfinance
from signal_engine import Signal, _hold, _ema

GOLD_TICKER = "GC=F"
DXY_TICKER  = "DX-Y.NYB"
PIP = 0.10

MIN_COUNT_TO_TRADE = 3
SL_ATR_MULT = 1.0
TP_ATR_MULT = 2.0
DXY_IMPULSE_LOOKBACK = 8
DXY_IMPULSE_THRESH_ATR = 1.5
DXY_COMPRESS_THRESH_ATR = 0.4
DXY_RETRACE_TRIGGER_PCT = 20.0
DXY_MAX_COILED_BARS = 20
EMA_PULLBACK_ATR = 0.3
EMA_CONT_BODY_ATR = 0.4
BRK_LOOKBACK = 20
BRK_RETEST_TOL_ATR = 0.15
IMPULSE_BODY_ATR = 1.0
FAST_LEN = 9
SLOW_LEN = 50
TOUCH_ATR = 0.2

TIER_CONTEXT = {
    "WATCH":    "19% historical win rate, PF 0.47 (M5 backtest) - use extra caution",
    "MODERATE": "31% historical win rate, PF 0.99 (M5 backtest) - close to breakeven",
    "STRONG":   "rare - not enough backtest samples yet to trust a number",
}

# ── Timeframe profiles ──────────────────────────────────────────────────
# Each profile scales EVERY reference timeframe up together, not just the
# entry candle - a "signal on H1" should use H1-relative context (daily EMA,
# daily momentum, weekly trend), not the same 15m/1h stack the M5 profile
# uses. min_bars is a sanity floor before trusting rolling calcs on that TF.
PROFILES = {
    # M1: Yahoo only serves 1-minute data for the last ~7 days - a real
    # data-source limit, not a design choice. Everything else scales down
    # proportionally from the M5 profile.
    "M1":  dict(pair="XAUUSD-GUIDE-M1",  tf_label="M1",  entry_interval="1m",  entry_period="7d",
                ema_htf_interval="5m",  ema_htf_period="5d",
                mom_interval="15m", mom_period="5d",   mom_ma_len=50,
                trend_interval="15m", trend_period="5d", trend_ma_len=20,
                min_bars=60),
    "M5":  dict(pair="XAUUSD-GUIDE-M5",  tf_label="M5",  entry_interval="5m",  entry_period="5d",
                ema_htf_interval="15m", ema_htf_period="5d",
                mom_interval="1h",  mom_period="1mo",  mom_ma_len=50,
                trend_interval="1h", trend_period="1mo", trend_ma_len=20,
                min_bars=60),
    "M15": dict(pair="XAUUSD-GUIDE-M15", tf_label="M15", entry_interval="15m", entry_period="1mo",
                ema_htf_interval="1h",  ema_htf_period="1mo",
                mom_interval="1d",  mom_period="6mo",  mom_ma_len=50,
                trend_interval="1d", trend_period="6mo", trend_ma_len=20,
                min_bars=60),
    "M30": dict(pair="XAUUSD-GUIDE-M30", tf_label="M30", entry_interval="30m", entry_period="1mo",
                ema_htf_interval="1h",  ema_htf_period="1mo",
                mom_interval="1d",  mom_period="6mo",  mom_ma_len=50,
                trend_interval="1d", trend_period="6mo", trend_ma_len=20,
                min_bars=60),
}


def _true_range_atr(df, n=14):
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift()).abs(),
        (df["low"] - df["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def _dxy_divergence_signal(gold_df, dxy_df, atr_series):
    """Stateful - walk through bars once, return (buy, sell) for the latest bar only."""
    if dxy_df.empty or len(dxy_df) < DXY_IMPULSE_LOOKBACK + DXY_MAX_COILED_BARS + 15:
        return False, False
    dxy_close = dxy_df["close"].reset_index(drop=True)
    dxy_atr = dxy_close.diff().abs().rolling(14).mean()

    n = min(len(dxy_close), len(gold_df))
    state = 0
    impulse_start = impulse_extreme = 0.0
    impulse_dir = 0
    coiled = 0
    buy = sell = False
    for i in range(DXY_IMPULSE_LOOKBACK + 14, n):
        dc = dxy_close.iloc[i]
        dclb = dxy_close.iloc[i - DXY_IMPULSE_LOOKBACK]
        datr = dxy_atr.iloc[i]
        if pd.isna(datr) or datr <= 0:
            continue
        dmove = dc - dclb
        dmove_atr = dmove / datr
        gmove = gold_df["close"].iloc[i] - gold_df["close"].iloc[i - DXY_IMPULSE_LOOKBACK]
        gatr = atr_series.iloc[i]
        if pd.isna(gatr) or gatr <= 0:
            continue
        gmove_atr = gmove / gatr

        buy = sell = False
        if state == 0:
            if abs(dmove_atr) >= DXY_IMPULSE_THRESH_ATR and abs(gmove_atr) <= DXY_COMPRESS_THRESH_ATR:
                state = 1
                impulse_dir = 1 if dmove > 0 else -1
                impulse_start = dclb
                impulse_extreme = dc
                coiled = 0
        elif state == 1:
            coiled += 1
            if (impulse_dir > 0 and dc > impulse_extreme) or (impulse_dir < 0 and dc < impulse_extreme):
                impulse_extreme = dc
            rng = abs(impulse_extreme - impulse_start)
            retr = abs(impulse_extreme - dc)
            retr_pct = (retr / rng * 100.0) if rng > 0 else 0.0
            if retr_pct >= DXY_RETRACE_TRIGGER_PCT:
                sig_dir = -impulse_dir
                buy, sell = (sig_dir > 0), (sig_dir < 0)
                state = 0
            elif coiled >= DXY_MAX_COILED_BARS:
                state = 0
    return buy, sell


def _ema_pullback_signal(gold_df, htf_ema_series, atr_series):
    c, o, h, l = gold_df["close"], gold_df["open"], gold_df["high"], gold_df["low"]
    i = len(gold_df) - 1
    atr = atr_series.iloc[i]
    if pd.isna(atr) or atr <= 0 or i < 2:
        return False, False
    htf_ema = htf_ema_series.iloc[-1]
    trend_up, trend_down = c.iloc[i] > htf_ema, c.iloc[i] < htf_ema
    near_up = htf_ema - EMA_PULLBACK_ATR*atr <= l.iloc[i] <= htf_ema + EMA_PULLBACK_ATR*atr
    near_down = htf_ema - EMA_PULLBACK_ATR*atr <= h.iloc[i] <= htf_ema + EMA_PULLBACK_ATR*atr
    cont_up = c.iloc[i] > o.iloc[i] and (c.iloc[i]-o.iloc[i]) >= EMA_CONT_BODY_ATR*atr and c.iloc[i] > h.iloc[i-1]
    cont_down = c.iloc[i] < o.iloc[i] and (o.iloc[i]-c.iloc[i]) >= EMA_CONT_BODY_ATR*atr and c.iloc[i] < l.iloc[i-1]
    return (trend_up and near_up and cont_up), (trend_down and near_down and cont_down)


def _break_retest_signal(gold_df, atr_series):
    """Stateful - walk through bars once."""
    c, h, l = gold_df["close"], gold_df["high"], gold_df["low"]
    n = len(gold_df)
    if n < BRK_LOOKBACK + 5:
        return False, False
    level, direction, awaiting = 0.0, 0, False
    buy = sell = False
    for i in range(BRK_LOOKBACK, n):
        atr = atr_series.iloc[i]
        if pd.isna(atr) or atr <= 0:
            continue
        recent_high = h.iloc[i-BRK_LOOKBACK:i].max()
        recent_low = l.iloc[i-BRK_LOOKBACK:i].min()
        buy = sell = False
        if not awaiting:
            if c.iloc[i] > recent_high:
                level, direction, awaiting = recent_high, 1, True
            elif c.iloc[i] < recent_low:
                level, direction, awaiting = recent_low, -1, True
        if awaiting and direction == 1:
            if l.iloc[i] <= level + BRK_RETEST_TOL_ATR*atr and c.iloc[i] > level:
                buy, awaiting = True, False
            elif c.iloc[i] < level - BRK_RETEST_TOL_ATR*atr:
                awaiting = False
        if awaiting and direction == -1:
            if h.iloc[i] >= level - BRK_RETEST_TOL_ATR*atr and c.iloc[i] < level:
                sell, awaiting = True, False
            elif c.iloc[i] > level + BRK_RETEST_TOL_ATR*atr:
                awaiting = False
    return buy, sell


def _htf_momentum_signal(gold_df, htf_ma_series, atr_series):
    c, o = gold_df["close"], gold_df["open"]
    i = len(gold_df) - 1
    atr = atr_series.iloc[i]
    if pd.isna(atr) or atr <= 0:
        return False, False
    htf_ma = htf_ma_series.iloc[-1]
    body = c.iloc[i] - o.iloc[i]
    return (c.iloc[i] > htf_ma and body >= IMPULSE_BODY_ATR*atr), \
           (c.iloc[i] < htf_ma and -body >= IMPULSE_BODY_ATR*atr)


def _ema_9_50_signal(gold_df, atr_series):
    c, o, h, l = gold_df["close"], gold_df["open"], gold_df["high"], gold_df["low"]
    ema9, ema50 = _ema(c, FAST_LEN), _ema(c, SLOW_LEN)
    i = len(gold_df) - 1
    atr = atr_series.iloc[i]
    if pd.isna(atr) or atr <= 0:
        return False, False
    e9, e50 = ema9.iloc[i], ema50.iloc[i]
    trend_up, trend_down = e9 > e50 and c.iloc[i] > e50, e9 < e50 and c.iloc[i] < e50
    touched_up = e9 - TOUCH_ATR*atr <= l.iloc[i] <= e9 + TOUCH_ATR*atr
    touched_down = e9 - TOUCH_ATR*atr <= h.iloc[i] <= e9 + TOUCH_ATR*atr
    buy = trend_up and touched_up and c.iloc[i] > o.iloc[i] and c.iloc[i] > e9
    sell = trend_down and touched_down and c.iloc[i] < o.iloc[i] and c.iloc[i] < e9
    return buy, sell


def _candle_pattern(gold_df):
    """Core pattern subset (matches the MT5 EA's tagging set)."""
    c, o, h, l = gold_df["close"], gold_df["open"], gold_df["high"], gold_df["low"]
    i = len(gold_df) - 1
    body = abs(c.iloc[i]-o.iloc[i]); rng = h.iloc[i]-l.iloc[i]
    upper = h.iloc[i]-max(c.iloc[i],o.iloc[i]); lower = min(c.iloc[i],o.iloc[i])-l.iloc[i]
    sma10 = c.rolling(10).mean().iloc[i]

    bull_engulf = c.iloc[i-1]<o.iloc[i-1] and c.iloc[i]>o.iloc[i] and o.iloc[i]<=c.iloc[i-1] and c.iloc[i]>=o.iloc[i-1]
    bear_engulf = c.iloc[i-1]>o.iloc[i-1] and c.iloc[i]<o.iloc[i] and o.iloc[i]>=c.iloc[i-1] and c.iloc[i]<=o.iloc[i-1]
    hammer = lower>=2*body and upper<=body*0.5 and body<=rng*0.35 and c.iloc[i]<sma10
    shoot_star = upper>=2*body and lower<=body*0.5 and body<=rng*0.35 and c.iloc[i]>sma10
    doji = body<=rng*0.1 and rng>0

    if bull_engulf: return "EngulfBull"
    if bear_engulf: return "EngulfBear"
    if hammer: return "Hammer"
    if shoot_star: return "ShootStar"
    if doji: return "Doji"
    return "none"


def scan_gold_manual_guide(profile_key: str = "M5") -> Signal:
    """Returns a single Signal for XAU/USD at the given timeframe profile
    (M5, M15, H1, or D1). Each profile scales its HTF/trend/momentum
    references proportionally - not just the entry candle - so this is a
    genuinely different signal per timeframe, not the same calculation
    relabeled."""
    p = PROFILES[profile_key]
    pair, label, category = p["pair"], f"XAU/USD {p['tf_label']} (Manual Guide)", "Forex"
    now_str = datetime.now(timezone.utc).isoformat()

    entry_df = fetch_yfinance(GOLD_TICKER, p["entry_interval"], p["entry_period"])
    if entry_df.empty or len(entry_df) < p["min_bars"]:
        return _hold(pair, label, category, f"Not enough {p['tf_label']} Gold data", now_str)

    dxy_df = fetch_yfinance(DXY_TICKER, p["entry_interval"], p["entry_period"])
    ema_htf_df = fetch_yfinance(GOLD_TICKER, p["ema_htf_interval"], p["ema_htf_period"])
    mom_df = fetch_yfinance(GOLD_TICKER, p["mom_interval"], p["mom_period"])
    trend_df = fetch_yfinance(GOLD_TICKER, p["trend_interval"], p["trend_period"])

    atr_series = _true_range_atr(entry_df, 14)
    if pd.isna(atr_series.iloc[-1]) or atr_series.iloc[-1] <= 0:
        return _hold(pair, label, category, "ATR not ready yet", now_str)

    htf_ema_series = _ema(ema_htf_df["close"], 20) if not ema_htf_df.empty else _ema(entry_df["close"], 20)
    mom_ma_series = mom_df["close"].rolling(p["mom_ma_len"]).mean() if not mom_df.empty else entry_df["close"].rolling(p["mom_ma_len"]).mean()

    dxy_buy, dxy_sell = _dxy_divergence_signal(entry_df, dxy_df, atr_series)
    ema_buy, ema_sell = _ema_pullback_signal(entry_df, htf_ema_series, atr_series)
    brk_buy, brk_sell = _break_retest_signal(entry_df, atr_series)
    htf_buy, htf_sell = _htf_momentum_signal(entry_df, mom_ma_series, atr_series)
    e950_buy, e950_sell = _ema_9_50_signal(entry_df, atr_series)
    pattern = _candle_pattern(entry_df)

    buy_count = sum([dxy_buy, ema_buy, brk_buy, htf_buy, e950_buy])
    sell_count = sum([dxy_sell, ema_sell, brk_sell, htf_sell, e950_sell])

    trend_bias = 0
    if not trend_df.empty and len(trend_df) >= p["trend_ma_len"]:
        t_ma = trend_df["close"].rolling(p["trend_ma_len"]).mean().iloc[-1]
        t_close = trend_df["close"].iloc[-1]
        trend_bias = 1 if t_close > t_ma else (-1 if t_close < t_ma else 0)

    show_buy = (trend_bias >= 0) and buy_count >= MIN_COUNT_TO_TRADE and buy_count >= sell_count
    show_sell = (trend_bias <= 0) and sell_count >= MIN_COUNT_TO_TRADE and sell_count > buy_count

    if not (show_buy or show_sell):
        return _hold(pair, label, category,
            f"No confluence yet | BUY {buy_count}/5, SELL {sell_count}/5 | Trend({p['trend_interval']}): "
            f"{'BULLISH' if trend_bias>0 else 'BEARISH' if trend_bias<0 else 'FLAT'}", now_str)

    atr = float(atr_series.iloc[-1])
    close = float(entry_df["close"].iloc[-1])
    direction = "BUY" if show_buy else "SELL"
    count = buy_count if show_buy else sell_count
    tier = "STRONG" if count >= 5 else "MODERATE" if count == 4 else "WATCH"

    sl = close - SL_ATR_MULT*atr if direction == "BUY" else close + SL_ATR_MULT*atr
    tp = close + TP_ATR_MULT*atr if direction == "BUY" else close - TP_ATR_MULT*atr

    backtest_note = "" if profile_key == "M5" else " (NOT separately backtested - informational only)"
    reasons = [
        f"{'🟢' if direction=='BUY' else '🔴'} {p['tf_label']} · {tier} tier ({count}/5 signals agree){backtest_note}",
        f"Confluence: DXY {'✓' if (dxy_buy or dxy_sell) else '-'} | EMA Pullback {'✓' if (ema_buy or ema_sell) else '-'} | "
        f"Break/Retest {'✓' if (brk_buy or brk_sell) else '-'} | HTF Momentum {'✓' if (htf_buy or htf_sell) else '-'} | "
        f"EMA9/50 {'✓' if (e950_buy or e950_sell) else '-'}",
        f"Candle pattern: {pattern}",
        f"📊 {TIER_CONTEXT[tier]}",
    ]

    return Signal(
        pair=pair, label=label, category=category,
        direction=direction, strength=tier,
        confidence=90 if tier == "STRONG" else 75 if tier == "MODERATE" else 65,
        entry=close, stop_loss=sl, take_profit_1=tp, take_profit_2=tp,
        sl_pips=abs(close-sl)/PIP, tp1_pips=abs(tp-close)/PIP, rr=TP_ATR_MULT/SL_ATR_MULT,
        reasons=reasons,
        warnings=[f"⚠️ {TIER_CONTEXT[tier]}"] if tier == "WATCH" else [],
        indicators={
            "dxy_move": "rising" if dxy_buy else "falling" if dxy_sell else "quiet",
            "trend": "bullish" if trend_bias > 0 else "bearish" if trend_bias < 0 else "flat",
            "timeframe": p["tf_label"],
        },
        action=f"{p['tf_label']} {direction} candidate ({tier} {count}/5) | Entry {close:.2f} TP {tp:.2f} SL {sl:.2f} - apply your own TA before entering",
        timestamp=now_str,
    )


def scan_all_gold_guide_timeframes():
    """Returns all 4 timeframe signals as a list, for the scan loop to iterate."""
    return [scan_gold_manual_guide(k) for k in PROFILES.keys()]
