"""
ATLAS — Main API Server
Deployable to Railway, Render, or any cloud host.
"""

from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler
import json, os
from datetime import datetime, timezone
from dataclasses import asdict

from signal_engine import scan_all, analyze, MARKETS
from market_data import fetch_market
from telegram_bot import send_signal, send_scan_summary, send_daily_morning, send_daily_evening
from gold_manual_guide import scan_gold_manual_guide

# ─── State ────────────────────────────────────────────────────
state = {
    "signals":    {},
    "last_scan":  None,
    "scanning":   False,
    "scan_count": 0,
    "signal_log": [],
    "daily_stats":{"signals":0,"wins":0,"losses":0},
}

def run_scan():
    if state["scanning"]: return
    state["scanning"] = True
    print(f"\n[ATLAS] Scanning all markets...")
    try:
        results = scan_all()
        for sig in results:
            state["signals"][sig["pair"]] = sig
            if sig.get("confidence",0) >= 65 and sig.get("direction") != "HOLD" and sig.get("strength") != "WEAK" and sig.get("pair") in ("XAUUSD","EURUSD"):
                send_signal(sig)
                state["signal_log"].append(sig)
                state["daily_stats"]["signals"] += 1
                if len(state["signal_log"]) > 100:
                    state["signal_log"] = state["signal_log"][-100:]

        # Gold Manual Trading Guide - own key (XAUUSD-GUIDE) so it doesn't
        # overwrite the regular XAUUSD entry. Sends whenever it has a real
        # candidate - its own tier + trend gating already applies, no need
        # to also filter it through the generic confidence threshold.
        try:
            guide_sig = asdict(scan_gold_manual_guide())
            state["signals"][guide_sig["pair"]] = guide_sig
            if guide_sig.get("direction") != "HOLD":
                send_signal(guide_sig)
                state["signal_log"].append(guide_sig)
                state["daily_stats"]["signals"] += 1
                if len(state["signal_log"]) > 100:
                    state["signal_log"] = state["signal_log"][-100:]
        except Exception as e:
            print(f"[ATLAS] Gold Manual Guide scan error: {e}")

        state["last_scan"]  = datetime.now(timezone.utc).isoformat()
        state["scan_count"] += 1
        print(f"[ATLAS] Scan #{state['scan_count']} complete.")
    except Exception as e:
        print(f"[ATLAS] Scan error: {e}")
    finally:
        state["scanning"] = False

def morning_brief():   send_daily_morning()
def evening_report():
    s = state["daily_stats"]
    send_daily_evening(s["signals"], s["wins"], s["losses"])
    state["daily_stats"] = {"signals":0,"wins":0,"losses":0}

scheduler = BackgroundScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(run_scan, "interval", minutes=3, id="scan")
    scheduler.add_job(morning_brief,  "cron", hour=6,  minute=45, id="morning")
    scheduler.add_job(evening_report, "cron", hour=21, minute=0,  id="evening")
    scheduler.start()
    print("✅ ATLAS online")
    # Initial scan runs after 30 seconds to allow healthcheck to pass first
    import threading
    threading.Timer(30, run_scan).start()
    yield
    scheduler.shutdown()

app = FastAPI(title="ATLAS Trading Signal System", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"])

@app.get("/api/health")
def health():
    return {"status":"online","system":"ATLAS v1.0",
            "last_scan":state["last_scan"],"scanning":state["scanning"],
            "scan_count":state["scan_count"],
            "timestamp":datetime.now(timezone.utc).isoformat()}

@app.get("/api/signals")
def get_signals():
    return JSONResponse(content={"signals":list(state["signals"].values()),
        "last_scan":state["last_scan"],"scanning":state["scanning"],
        "count":len(state["signals"])})

@app.get("/api/signal/{pair}")
def get_signal(pair: str):
    pair = pair.upper()
    if pair not in MARKETS:
        return JSONResponse(status_code=400, content={"error":f"Unknown pair: {pair}"})
    df  = fetch_market(pair, "5min")
    sig = analyze(df, pair)
    result = asdict(sig)
    state["signals"][pair] = result
    if result.get("confidence",0) >= 65 and result.get("direction") != "HOLD" and result.get("strength") != "WEAK" and result.get("pair") in ("XAUUSD","EURUSD"):
        send_signal(result)
    return JSONResponse(content=result)

@app.post("/api/scan")
def trigger_scan(background_tasks: BackgroundTasks):
    if state["scanning"]:
        return JSONResponse(content={"status":"already_scanning"})
    background_tasks.add_task(run_scan)
    return JSONResponse(content={"status":"scan_started"})

@app.get("/api/markets")
def get_markets():
    return JSONResponse(content={"markets":list(MARKETS.keys()),"details":MARKETS})

@app.get("/api/log")
def signal_log():
    return JSONResponse(content={"log":state["signal_log"][-20:]})

@app.post("/api/outcome")
async def update_outcome(body: dict):
    outcome = body.get("outcome","").upper()
    if outcome == "WIN":   state["daily_stats"]["wins"]   += 1
    elif outcome == "LOSS": state["daily_stats"]["losses"] += 1
    return {"status":"ok"}

@app.get("/api/stats")
def get_stats():
    return JSONResponse(content={"daily":state["daily_stats"]})

# ─── Backtest — run once, download as CSV (no shell needed) ────
_backtest_cache = {}  # keyed by (strategy, period) -> (trades, candles)

def _ensure_backtest(strategy: str = "gold", period: str = None):
    if period is None:
        period = "90d" if strategy == "gold" else "60d"  # 5m data's Yahoo lookback limit
    interval = "1h" if strategy == "gold" else "5m"
    key = (strategy, period)
    if key not in _backtest_cache:
        from backtest import run_backtest
        trades, df = run_backtest(strategy=strategy, period=period, interval=interval)
        _backtest_cache[key] = (trades, df)
    return _backtest_cache[key]

@app.get("/api/backtest/run")
def api_backtest_run(strategy: str = "gold", period: str = None):
    """Force a fresh backtest run for this strategy/period (clears its cache first)."""
    resolved_period = period or ("90d" if strategy == "gold" else "60d")
    key = (strategy, resolved_period)
    _backtest_cache.pop(key, None)
    trades, df = _ensure_backtest(strategy, resolved_period)
    from backtest import report
    summary = report(trades, df, strategy=strategy)
    return {"status": "done", "strategy": strategy, "period": resolved_period,
            "candles": len(df), **(summary or {"trades": 0, "note": "no trades generated"})}

@app.get("/api/backtest/compare")
def api_backtest_compare():
    """
    Ranks every strategy currently in the cache by profit factor, using
    whatever was last run via /api/backtest/run for each. Doesn't run
    anything new — instant, since it just reads what's already there.
    Run /api/backtest/run?strategy=X for each strategy you want included
    before calling this.
    """
    from backtest import report
    if not _backtest_cache:
        return {"error": "Nothing cached yet. Visit /api/backtest/run?strategy=X for each "
                          "strategy first (gold, scalp, meanrev), then call this."}

    results = []
    for (strategy, period), (trades, df) in _backtest_cache.items():
        summary = report(trades, df, strategy=strategy) if not trades.empty else None
        if summary:
            results.append({"strategy": strategy, "period": period, **summary})
        else:
            results.append({"strategy": strategy, "period": period, "trades": 0, "note": "no trades"})

    # Rank by profit factor, treating "no trades" and infinite PF sensibly
    def rank_key(r):
        pf = r.get("profit_factor")
        if pf is None:
            return -1  # no trades or undefined PF sinks to bottom
        return pf
    results.sort(key=rank_key, reverse=True)

    return {"ranked_by": "profit_factor (highest first)", "results": results}

@app.get("/api/backtest/run-all")
def api_backtest_run_all():
    """
    Convenience: runs gold, scalp, and meanrev fresh, one after another,
    then returns the ranked comparison. WARNING: this can take several
    minutes total and risks timing out on Render's free tier — prefer
    running each via /api/backtest/run separately if this fails.
    """
    from backtest import report
    for strategy in ("gold", "scalp", "meanrev"):
        period = "90d" if strategy == "gold" else "60d"
        key = (strategy, period)
        _backtest_cache.pop(key, None)
        _ensure_backtest(strategy, period)
    return api_backtest_compare()

@app.get("/api/backtest/trades.csv")
def api_backtest_trades_csv(strategy: str = "gold", period: str = None):
    trades, _ = _ensure_backtest(strategy, period)
    return PlainTextResponse(trades.to_csv(index=False), media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=backtest_trades_{strategy}.csv"})

@app.get("/api/backtest/candles.csv")
def api_backtest_candles_csv(strategy: str = "gold", period: str = None):
    _, df = _ensure_backtest(strategy, period)
    return PlainTextResponse(df.to_csv(index=False), media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=backtest_candles_{strategy}.csv"})

# Serve frontend
dist_path = "/app/dist"
if os.path.exists(dist_path):
    app.mount("/", StaticFiles(directory=dist_path, html=True), name="static")
else:
    @app.get("/")
    def root():
        return {"status":"online","message":"ATLAS API running."}
