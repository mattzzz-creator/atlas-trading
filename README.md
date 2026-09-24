# ATLAS Gold Signals

Gold (XAU/USD) signals pushed to Telegram, computed on your **MT5 broker's live price**.
Signals only: the EA never places, modifies or closes an order. You decide the trade with your own TA.

Everything lives in one file: `ATLAS_GOLD_SIGNALS.mq5`.

## What it does

- Watches four timeframe profiles (M1, M5, M15, M30); only M15 and M30 are on by default (see Backtest results). Each is evaluated on **closed candles only**, so signals do not repaint.
- Fires when at least 3 of 5 signals agree (DXY divergence, EMA pullback, break and retest, higher-timeframe momentum, EMA9/50 touch), the higher-timeframe trend does not disagree, and the timeframe is not in cooldown.
- Each Telegram alert has live entry (ask for BUY, bid for SELL), stop loss and take profit (1 ATR / 3 ATR by default), spread, trend, which signals agreed, and a PHT timestamp.
- **Follow-ups:** it tracks every signal and tells you in Telegram when TP or SL is hit (or when it expires), with the result in R.
- **News warning:** uses the MT5 economic calendar. A signal near a high-impact USD release gets a warning line, and you get a standalone heads-up before the release.
- Every signal and outcome is logged to `Common\Files\atlas_gold_signals.csv`.

## Setup

1. **Telegram bot.** In Telegram, open `@BotFather`, send `/newbot`, and copy the token. Add the bot to your group. To get the chat id, send a message in the group and open `https://api.telegram.org/bot<TOKEN>/getUpdates`, then read `"chat":{"id":...}`.
2. **Allow WebRequest in MT5.** Tools > Options > Expert Advisors > tick *Allow WebRequest for listed URL* and add `https://api.telegram.org`.
3. **Install the EA.** In MT5 choose File > Open Data Folder, then copy `ATLAS_GOLD_SIGNALS.mq5` into `MQL5\Experts`. Open it in MetaEditor and press F7 to compile. Fix any errors it reports before continuing.
4. **Attach it** to a gold chart (XAUUSD or GOLD#, any timeframe). Fill in `TG_TOKEN` and `TG_CHAT_ID` in the inputs and keep Algo Trading enabled so the EA runs (it does not trade).
5. Optional: set `DXY_SYMBOL` to your broker's dollar index symbol (for example `DXY` or `USDX`). Left empty, the DXY signal is off and only 4 signals can agree.
6. Keep MT5 running. A cheap Windows VPS is the usual way to get 24/5 alerts.

Your bot token is stored in the EA inputs on your own machine, not in this repo. Do not share a `.set` file that contains it.

## Backtesting (MT5 Strategy Tester)

The EA has the same signal code for live and test, so the backtest and the live alerts cannot drift apart.

1. View > Strategy Tester. Expert: `ATLAS_GOLD_SIGNALS`. Symbol: your gold symbol.
2. Model: **Every tick based on real ticks**. Use this model, because signals are tracked tick by tick.
3. Choose at least 1 year, ideally 2 or more. The timeframe on the tester does not matter, since the EA reads all four profiles itself.
4. Run. Results print in the **Journal** tab at the end: signals, TP/SL/expired counts, win rate, net R and profit factor for each timeframe and tier. Read these, not the tester's balance graph, because the EA does not open trades.
5. A full log is written to `Common\Files\tester_atlas_gold_signals.csv`.

How to read it: at RR 1:3 the break-even win rate is 25% (at RR 1:2 it is 33.3%). Entry is at ask/bid, so spread is already included. A profit factor above 1 with a few hundred signals is meaningful; a few dozen signals is not.

Things to know:
- The news calendar and Telegram sending are turned off in the tester by MT5 itself.
- With `DXY_SYMBOL` set, the tester needs history for that symbol. Run once without it and once with it to compare.
- Try `WINDOW_BARS` 0, 3 and 5, and `TP_ATR_MULT` 1.5, 2, 3. Judge on data the settings were not tuned on.

## Backtest results (XM GOLD#, real ticks)

Test window Jan 2025 to 22 Sep 2026. Results are in R (1R = the stop distance), entries at ask/bid so spread is included.

| Profile / setting | Result |
|---|---|
| M1 profile, TP 2 ATR (Jun to Sep 2026) | about -159R, 29.9% win rate: dropped |
| M5 profile, 20 months | about -137R: dropped |
| M15 + M30, TP 1.5 ATR | 2025 +45R, 2026 -11R |
| M15 + M30, TP 2 ATR | 2025 +64R, 2026 +8R |
| M15 + M30, TP 3 ATR (default) | 2025 +77R, 2026 +36R (about 590 signals, about 0.19R per signal) |

The edge is modest and comes mostly from 2025, when gold trended up. Treat it as unproven and forward-test on a demo account first.

`ATLAS_MICRO_SCALP.mq5` is a research simulator for a 1-minute liquidity-sweep + fair-value-gap scalp (virtual trades, no orders). On gold it lost in every variant (PF 0.70 with an 8-minute exit, 0.74 with no time exit, 660 trades over 20 months). It is kept only so the test can be reproduced.

## Main inputs

| Input | Default | Meaning |
|---|---|---|
| `MIN_COUNT` | 3 | Signals that must agree |
| `WINDOW_BARS` | 5 | How long a signal keeps counting after it fires |
| `COOLDOWN_BARS` | 10 | Quiet period per timeframe after an alert |
| `USE_M1` / `USE_M5` | false / false | Timeframe profiles switched off by default |
| `SL_ATR_MULT` / `TP_ATR_MULT` | 1.0 / 3.0 | Stop and target in ATR |
| `MAX_SPREAD` | 0 (off) | Skip alerts when spread is wider than this |
| `NEWS_BLOCK` | false | Suppress signals while high-impact news is near |
| `TRACK_HOURS` | 24 | Mark a signal expired after this long |

## Notes on the logic

The signal rules come from the earlier Manual Guide port, with these fixes:
- Higher-timeframe values (EMA20, SMA50, SMA20) always use the last **completed** higher-timeframe candle. The old version indexed them by row number, which was misaligned.
- Break and retest is only checked on candles after the breakout candle, and expires after 30 bars.
- Signals use live broker prices instead of Yahoo gold futures, which removes the delay and the futures-to-spot price offset.

The EUR/USD strategies, the web dashboard, the API server and the Yahoo data code were removed. They remain in the git history.
