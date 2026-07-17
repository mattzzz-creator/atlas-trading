"""
ATLAS — Telegram Signal Bot
Sends BUY/SELL signals to your trading group.
Setup: Create bot via @BotFather, add to group, get chat ID.
"""

import os
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")


def send_message(text: str) -> bool:
    if not BOT_TOKEN or not CHAT_ID:
        print("[Telegram] No bot token or chat ID configured.")
        return False
    try:
        url  = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        resp = requests.post(url, json={
            "chat_id":    CHAT_ID,
            "text":       text,
            "parse_mode": "HTML",
        }, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        print(f"[Telegram] Send error: {e}")
        return False


def format_signal(sig: dict) -> str:
    """Format a signal for Telegram."""
    dir   = sig.get("direction","HOLD")
    label = sig.get("label", sig.get("pair",""))
    conf  = sig.get("confidence",0)
    entry = sig.get("entry",0)
    sl    = sig.get("stop_loss",0)
    tp1   = sig.get("take_profit_1",0)
    tp2   = sig.get("take_profit_2",0)
    sl_p  = sig.get("sl_pips",0)
    tp1_p = sig.get("tp1_pips",0)
    cat   = sig.get("category","")
    str_  = sig.get("strength","")
    ind   = sig.get("indicators",{})
    ts    = sig.get("timestamp","")
    reasons = sig.get("reasons",[])

    if dir == "HOLD":
        return ""

    emoji = "🟢" if dir=="BUY" else "🔴"
    cat_emoji = {"Forex":"💱","Stocks":"📈","Crypto":"₿"}.get(cat,"📊")

    reasons_text = "\n".join(f"  • {r}" for r in reasons[:3])

    time_str = ""
    try:
        dt = datetime.fromisoformat(ts.replace("Z","+00:00"))
        time_str = dt.strftime("%H:%M UTC")
    except: pass

    msg = f"""
{emoji} <b>ATLAS SIGNAL — {dir}</b> {cat_emoji}

<b>{label}</b> | {str_} | {conf}% confidence

💰 <b>Entry:</b>  <code>{entry:.5f}</code>
🛑 <b>Stop Loss:</b> <code>{sl:.5f}</code> ({sl_p} pips)
✅ <b>TP1:</b>   <code>{tp1:.5f}</code> ({tp1_p} pips)
🎯 <b>TP2:</b>   <code>{tp2:.5f}</code>

📊 RSI: {ind.get("rsi","—")} | EMA: {"↑" if ind.get("ema9",0)>ind.get("ema21",0) else "↓"}

<b>Why:</b>
{reasons_text}

⏰ {time_str}
━━━━━━━━━━━━━━━━
<i>ATLAS Trading System</i>
""".strip()
    return msg


def send_signal(sig: dict) -> bool:
    """Send a signal to Telegram if confidence >= 65%."""
    if sig.get("direction") == "HOLD": return False
    if sig.get("confidence",0) < 65:   return False
    msg = format_signal(sig)
    if not msg: return False
    return send_message(msg)


def send_scan_summary(signals: list) -> bool:
    """Send a summary of all signals after a full scan."""
    active = [s for s in signals if s.get("direction") != "HOLD"]
    if not active:
        return send_message("⏸ <b>ATLAS SCAN COMPLETE</b>\n\nNo active signals right now. Markets are ranging. Wait for a clearer setup.")

    lines = ["⚡ <b>ATLAS SCAN COMPLETE</b>\n"]
    for s in active:
        d = s["direction"]; c = s["confidence"]
        e = "🟢" if d=="BUY" else "🔴"
        lines.append(f"{e} <b>{s['label']}</b> — {d} ({c}%)")

    lines.append(f"\n{len(active)} signal(s) detected. Check dashboard for full details.")
    return send_message("\n".join(lines))


def send_daily_morning():
    """Morning briefing message."""
    msg = """
🌅 <b>ATLAS MORNING BRIEFING</b>

Good morning traders! Markets are opening.

📋 <b>Today's Focus:</b>
• London session: 7:00–16:00 UTC
• New York session: 12:00–21:00 UTC  
• Highest probability: 12:00–16:00 UTC overlap

⚡ ATLAS is scanning all markets every 5 minutes.
You will be alerted for every signal 65%+ confidence.

💡 <b>Reminder:</b> Never risk more than 1-2% per trade.
Set your stop loss BEFORE entering.

Good luck today. — ATLAS
""".strip()
    return send_message(msg)


def send_daily_evening(signals_today: int, wins: int, losses: int):
    """Evening performance summary."""
    wr = round(wins/(wins+losses)*100,1) if (wins+losses)>0 else 0
    verdict = "✅ Good day!" if wr>=50 else "⚠️ Tough day — review your trades."
    msg = f"""
🌙 <b>ATLAS EVENING REPORT</b>

{verdict}

📊 <b>Today's Results:</b>
• Signals sent: {signals_today}
• Wins: {wins} ✅
• Losses: {losses} ❌
• Win rate: {wr}%

See you tomorrow. — ATLAS
""".strip()
    return send_message(msg)
