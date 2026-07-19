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
            if sig.get("confidence",0) >= 65 and sig.get("direction") != "HOLD" and sig.get("strength") != "WEAK" and sig.get("pair") == "XAUUSD":
                send_signal(sig)
                state["signal_log"].append(sig)
                state["daily_stats"]["signals"] += 1
                if len(state["signal_log"]) > 100:
                    state["signal_log"] = state["signal_log"][-100:]
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
    if result.get("confidence",0) >= 65 and result.get("direction") != "HOLD" and result.get("strength") != "WEAK" and result.get("pair") == "XAUUSD":
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
_backtest_cache = {}  # keyed by period string, e.g. "90d" -> (trades, candles)

def _ensure_backtest(period: str = "90d"):
    if period not in _backtest_cache:
        from backtest import run_backtest
        trades, df = run_backtest(period=period, interval="1h")
        _backtest_cache[period] = (trades, df)
    return _backtest_cache[period]

@app.get("/api/backtest/run")
def api_backtest_run(period: str = "90d"):
    """Force a fresh backtest run for this period (clears its cache first)."""
    _backtest_cache.pop(period, None)
    trades, df = _ensure_backtest(period)
    return {"status": "done", "period": period, "trades": len(trades), "candles": len(df)}

@app.get("/api/backtest/trades.csv")
def api_backtest_trades_csv(period: str = "90d"):
    trades, _ = _ensure_backtest(period)
    return PlainTextResponse(trades.to_csv(index=False), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=backtest_trades.csv"})

@app.get("/api/backtest/candles.csv")
def api_backtest_candles_csv(period: str = "90d"):
    _, df = _ensure_backtest(period)
    return PlainTextResponse(df.to_csv(index=False), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=backtest_candles.csv"})

# Serve frontend
dist_path = "/app/dist"
if os.path.exists(dist_path):
    app.mount("/", StaticFiles(directory=dist_path, html=True), name="static")
else:
    @app.get("/")
    def root():
        return {"status":"online","message":"ATLAS API running."}
