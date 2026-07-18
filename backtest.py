"""
ATLAS — Backtest for analyze_gold() (London Breakout strategy)

Walks real historical XAUUSD (GC=F) candles hour by hour, calling the
ACTUAL production analyze_gold() function at each step with only the data
that would have been available at that moment (no lookahead). When a
BUY/SELL fires, simulates the fill against subsequent candles to see
whether SL or TP1 is hit first — same as live trading (one position at a
time, matching HasOpenTrade() in the EA).
"""

import pandas as pd
from datetime import datetime, timezone
from market_data import fetch_yfinance
from signal_engine import analyze_gold

PIP = 0.10


def run_backtest(period="90d", interval="1h"):
    print(f"Fetching {period} of {interval} GC=F data from Yahoo Finance...")
    df = fetch_yfinance("GC=F", interval, period)
    if df.empty:
        print("No data returned — aborting.")
        return None
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
        sig = analyze_gold(window, as_of=as_of)
        if sig.direction in ("BUY", "SELL") and sig.confidence >= MIN_CONFIDENCE and sig.strength != "WEAK":
            open_trade = {
                "time": as_of, "dir": sig.direction,
                "entry": sig.entry, "sl": sig.stop_loss, "tp1": sig.take_profit_1,
                "confidence": sig.confidence,
            }

    return pd.DataFrame(trades), df


def report(trades: pd.DataFrame, df: pd.DataFrame):
    df.to_csv("backtest_candles.csv", index=False)
    if trades.empty:
        print("\nNo trades were generated in this period.")
        print("Candle data still saved to backtest_candles.csv for inspection.")
        trades.to_csv("backtest_trades.csv", index=False)
        return

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
    print("ATLAS GOLD — BACKTEST REPORT")
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

    trades.to_csv("backtest_trades.csv", index=False)
    print("\nFull trade log saved to backtest_trades.csv")
    print("Candle data saved to backtest_candles.csv (needed by the replay viewer)")


if __name__ == "__main__":
    trades, df = run_backtest(period="90d", interval="1h")
    if trades is not None:
        report(trades, df)
