"""
ATLAS — Backtest for analyze_gold() and analyze_scalp()

Walks real historical candles bar by bar, calling the ACTUAL production
analyze function at each step with only the data that would have been
available at that moment (no lookahead). When a BUY/SELL fires, simulates
the fill against subsequent candles to see whether SL or TP1 is hit first —
same as live trading (one position at a time, matching HasOpenTrade() in
the EA).
"""

import pandas as pd
import math, random
from datetime import datetime, timezone
from market_data import fetch_yfinance
from signal_engine import analyze_gold, analyze_scalp, analyze_meanrev, analyze_ict

STRATEGIES = {
    "gold":    {"ticker": "GC=F",     "pip": 0.10,   "fn": analyze_gold},
    "scalp":   {"ticker": "EURUSD=X", "pip": 0.0001, "fn": analyze_scalp},
    "meanrev": {"ticker": "EURUSD=X", "pip": 0.0001, "fn": analyze_meanrev},
    "ict":     {"ticker": "EURUSD=X", "pip": 0.0001, "fn": analyze_ict},
}


def run_backtest(strategy="gold", period="90d", interval="1h"):
    cfg = STRATEGIES[strategy]
    ticker, PIP, analyze_fn = cfg["ticker"], cfg["pip"], cfg["fn"]

    print(f"[{strategy}] Fetching {period} of {interval} {ticker} data from Yahoo Finance...")
    df = fetch_yfinance(ticker, interval, period)
    if df.empty:
        print("No data returned — aborting.")
        return None, None
    df["time"] = pd.to_datetime(df["time"]).dt.tz_localize(None)
    df = df.sort_values("time").reset_index(drop=True)
    print(f"Loaded {len(df)} candles: {df['time'].iloc[0]} -> {df['time'].iloc[-1]}")

    trades = []
    open_trade = None  # dict with entry/sl/tp1/direction/open_idx

    MIN_CONFIDENCE = 65

    for i in range(30, len(df)):
        as_of = df["time"].iloc[i]
        window = df.iloc[: i + 1]  # only data up to & including this candle — no lookahead

        # ── Manage an open position first ──────────────────────
        if open_trade is not None:
            bar = df.iloc[i]
            hit_sl = bar["low"] <= open_trade["sl"] if open_trade["dir"] == "BUY" else bar["high"] >= open_trade["sl"]
            hit_tp = bar["high"] >= open_trade["tp1"] if open_trade["dir"] == "BUY" else bar["low"] <= open_trade["tp1"]

            outcome = None
            if hit_sl and hit_tp:
                # Conservative assumption: SL hit first if both touched same candle
                outcome = "LOSS"
            elif hit_sl:
                outcome = "LOSS"
            elif hit_tp:
                outcome = "WIN"

            if outcome:
                pips = (abs(open_trade["sl"] - open_trade["entry"]) if outcome == "LOSS"
                         else abs(open_trade["tp1"] - open_trade["entry"])) / PIP
                if outcome == "LOSS":
                    pips = -pips
                trades.append({
                    "open_time":  open_trade["time"],
                    "close_time": as_of,
                    "direction":  open_trade["dir"],
                    "entry":      open_trade["entry"],
                    "sl":         open_trade["sl"],
                    "tp1":        open_trade["tp1"],
                    "confidence": open_trade["confidence"],
                    "outcome":    outcome,
                    "pips":       round(pips, 1),
                })
                open_trade = None
            continue  # don't look for new signal while a trade is open — matches EA behavior

        # ── No open position — check for a new signal ──────────
        sig = analyze_fn(window, as_of=as_of)
        if sig.direction in ("BUY", "SELL") and sig.confidence >= MIN_CONFIDENCE and sig.strength != "WEAK":
            open_trade = {
                "time": as_of, "dir": sig.direction,
                "entry": sig.entry, "sl": sig.stop_loss, "tp1": sig.take_profit_1,
                "confidence": sig.confidence,
            }

    return pd.DataFrame(trades), df


def _binomial_test_greater(k, n, p):
    """
    Exact one-sided binomial test (pure stdlib, no scipy needed).
    Returns P(X >= k) where X ~ Binomial(n, p) — i.e. the probability of
    seeing at least this many wins by pure chance if the TRUE win rate
    were exactly the breakeven rate p. A small p-value means the result
    is unlikely to be luck.
    """
    return sum(math.comb(n, i) * (p**i) * ((1-p)**(n-i)) for i in range(k, n+1))


def _bootstrap_pips(pips_list, n_iter=3000, seed=42):
    """
    Resample the actual trade outcomes (with replacement) n_iter times to
    build a realistic range of what total pips could have looked like —
    instead of trusting the one specific sequence we happened to get.
    Returns (5th percentile, 50th/median, 95th percentile, % of runs profitable).
    """
    rng = random.Random(seed)
    n = len(pips_list)
    totals = []
    for _ in range(n_iter):
        sample = rng.choices(pips_list, k=n)
        totals.append(sum(sample))
    totals.sort()
    p5  = totals[int(0.05 * n_iter)]
    p50 = totals[int(0.50 * n_iter)]
    p95 = totals[int(0.95 * n_iter)]
    pct_profitable = sum(1 for t in totals if t > 0) / n_iter * 100
    return p5, p50, p95, pct_profitable


def significance_report(trades: pd.DataFrame):
    """
    Answers: 'is this win rate/profit actually meaningful, or could it be
    luck given how few trades we have?' Two independent checks:
    1. Binomial test — is win rate statistically above the breakeven rate
       this risk-reward ratio requires?
    2. Bootstrap — resample the real trades thousands of times to see the
       realistic spread of outcomes, not just the one total we observed.
    """
    n = len(trades)
    wins = int((trades["outcome"] == "WIN").sum())

    # Per-trade RR from actual entry/sl/tp1 (handles both fixed and variable RR strategies)
    rrs = []
    for _, r in trades.iterrows():
        risk = abs(r["entry"] - r["sl"])
        reward = abs(r["tp1"] - r["entry"])
        if risk > 0:
            rrs.append(reward / risk)
    avg_rr = sum(rrs) / len(rrs) if rrs else 1.5
    breakeven_wr = 1 / (1 + avg_rr)

    p_value = _binomial_test_greater(wins, n, breakeven_wr)
    p5, p50, p95, pct_profitable = _bootstrap_pips(trades["pips"].tolist())

    print("\n" + "-" * 50)
    print("STATISTICAL SIGNIFICANCE (is this real, or luck?)")
    print("-" * 50)
    print(f"Avg reward:risk:          1:{avg_rr:.2f}")
    print(f"Breakeven win rate:       {breakeven_wr*100:.1f}%")
    print(f"Actual win rate:          {wins/n*100:.1f}%  ({wins}/{n})")
    print(f"Binomial test p-value:    {p_value:.4f}", end="  ")
    if p_value < 0.05:
        print("← statistically significant (< 0.05)")
    elif p_value < 0.15:
        print("← borderline, not fully conclusive")
    else:
        print("← NOT significant — could easily be chance")
    print(f"\nBootstrap (3000 resamples of these {n} trades):")
    print(f"  5th percentile:  {p5:+.1f} pips")
    print(f"  Median:          {p50:+.1f} pips")
    print(f"  95th percentile: {p95:+.1f} pips")
    print(f"  % of resamples profitable: {pct_profitable:.1f}%")
    print("-" * 50)
    print("Read this as: even resampling the SAME trades, how often do we")
    print("still end up net profitable? Low % or a wide/negative 5th")
    print("percentile means the result is fragile, not robust.")
    print("-" * 50)

    return {
        "avg_reward_to_risk": round(avg_rr, 2),
        "breakeven_win_rate_pct": round(breakeven_wr*100, 1),
        "actual_win_rate_pct": round(wins/n*100, 1),
        "p_value": round(p_value, 4),
        "significant": p_value < 0.05,
        "bootstrap_5th_pct_pips": round(p5, 1),
        "bootstrap_median_pips": round(p50, 1),
        "bootstrap_95th_pct_pips": round(p95, 1),
        "pct_resamples_profitable": round(pct_profitable, 1),
    }


def report(trades: pd.DataFrame, df: pd.DataFrame, strategy="gold"):
    candles_file = f"backtest_candles_{strategy}.csv"
    trades_file  = f"backtest_trades_{strategy}.csv"

    df.to_csv(candles_file, index=False)
    if trades.empty:
        print("\nNo trades were generated in this period.")
        print(f"Candle data still saved to {candles_file} for inspection.")
        trades.to_csv(trades_file, index=False)
        return None

    n          = len(trades)
    wins       = (trades["outcome"] == "WIN").sum()
    losses     = (trades["outcome"] == "LOSS").sum()
    win_rate   = wins / n * 100
    total_pips = trades["pips"].sum()
    gross_win  = trades.loc[trades["pips"] > 0, "pips"].sum()
    gross_loss = abs(trades.loc[trades["pips"] < 0, "pips"].sum())
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else float("inf")
    avg_win    = trades.loc[trades["pips"] > 0, "pips"].mean() if wins else 0
    avg_loss   = trades.loc[trades["pips"] < 0, "pips"].mean() if losses else 0

    # Equity curve in pips, running
    equity = trades["pips"].cumsum()
    running_max = equity.cummax()
    drawdown = equity - running_max
    max_dd = drawdown.min()

    days = max((df["time"].iloc[-1] - df["time"].iloc[0]).days, 1)
    trades_per_day = n / days

    print("\n" + "=" * 50)
    print(f"ATLAS {strategy.upper()} — BACKTEST REPORT")
    print("=" * 50)
    print(f"Period:            {df['time'].iloc[0].date()} -> {df['time'].iloc[-1].date()}  ({days} days)")
    print(f"Total trades:      {n}")
    print(f"Trades/day (avg):  {trades_per_day:.2f}")
    print(f"Wins / Losses:     {wins} / {losses}")
    print(f"Win rate:          {win_rate:.1f}%")
    print(f"Avg win / loss:    +{avg_win:.1f} pips / {avg_loss:.1f} pips")
    print(f"Total pips:        {total_pips:+.1f}")
    print(f"Profit factor:     {profit_factor:.2f}")
    print(f"Max drawdown:      {max_dd:.1f} pips")
    print("=" * 50)

    significance = significance_report(trades)

    trades.to_csv(trades_file, index=False)
    print(f"\nFull trade log saved to {trades_file}")
    print(f"Candle data saved to {candles_file} (needed by the replay viewer)")

    return {
        "trades": int(n), "wins": int(wins), "losses": int(losses),
        "win_rate_pct": round(win_rate, 1), "total_pips": round(float(total_pips), 1),
        "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else None,
        "max_drawdown_pips": round(float(max_dd), 1),
        "significance": significance,
    }


if __name__ == "__main__":
    import sys
    strategy = sys.argv[1] if len(sys.argv) > 1 else "gold"
    period   = "90d" if strategy == "gold" else "30d"  # 5m data has a shorter Yahoo lookback limit
    interval = "1h" if strategy == "gold" else "5m"
    trades, df = run_backtest(strategy=strategy, period=period, interval=interval)
    if trades is not None:
        report(trades, df, strategy=strategy)
