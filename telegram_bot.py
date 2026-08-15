"""
ATLAS — Telegram Signal Bot (Gold-only)
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
    """Format a Gold Manual Guide signal for Telegram.
    label already includes the timeframe (e.g. "XAU/USD H1 (Manual Guide)"),
    so direction + label together cover "which timeframe, which direction."
    Prices use 2 decimals - correct for gold, not the 5-decimal forex format
    this used to have."""
    direction = sig.get("direction", "HOLD")
    if direction == "HOLD":
        return ""

    label = sig.get("label", sig.get("pair", ""))
    strength = sig.get("strength", "")
    conf = sig.get("confidence", 0)
    entry = sig.get("entry", 0)
    sl = sig.get("stop_loss", 0)
    tp = sig.get("take_profit_1", 0)
    ind = sig.get("indicators", {})
    reasons = sig.get("reasons", [])
    ts = sig.get("timestamp", "")

    emoji = "🟢" if direction == "BUY" else "🔴"

    time_str = ""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        time_str = dt.strftime("%H:%M UTC")
    except Exception:
        pass

    context_line = ""
    if ind.get("trend") or ind.get("dxy_move"):
        context_line = f"📊 Trend: {ind.get('trend','—')} | DXY: {ind.get('dxy_move','—')}\n\n"

    reasons_text = "\n".join(f"  • {r}" for r in reasons[:3])

    msg = f"""
{emoji} <b>ATLAS GOLD SIGNAL — {direction}</b>

<b>{label}</b> | {strength} | {conf}% confidence

💰 <b>Entry:</b>  <code>{entry:.2f}</code>
🛑 <b>Stop Loss:</b> <code>{sl:.2f}</code>
🎯 <b>Take Profit:</b> <code>{tp:.2f}</code>

{context_line}<b>Why:</b>
{reasons_text}

⏰ {time_str}
━━━━━━━━━━━━━━━━
<i>ATLAS Trading System — apply your own TA before entering</i>
""".strip()
    return msg


def send_signal(sig: dict) -> bool:
    """Send a signal to Telegram if it's an actual candidate (not HOLD).
    Gold Guide signals already carry their own tier gating (WATCH/MODERATE/
    STRONG at 3+/5 confluence) - no extra confidence filter needed here."""
    if sig.get("direction") == "HOLD":
        return False
    msg = format_signal(sig)
    if not msg:
        return False
    return send_message(msg)


def send_scan_summary(signals: list) -> bool:
    """Send a summary of all active Gold Guide signals after a scan."""
    active = [s for s in signals if s.get("direction") != "HOLD"]
    if not active:
        return send_message("⏸ <b>ATLAS SCAN COMPLETE</b>\n\nNo active Gold signals right now.")

    lines = ["⚡ <b>ATLAS SCAN COMPLETE</b>\n"]
    for s in active:
        d, c = s["direction"], s.get("strength", "")
        e = "🟢" if d == "BUY" else "🔴"
        lines.append(f"{e} <b>{s['label']}</b> — {d} ({c})")

    lines.append(f"\n{len(active)} signal(s) detected. Check dashboard for full details.")
    return send_message("\n".join(lines))


def send_daily_morning():
    """Morning briefing message."""
    msg = """
🌅 <b>ATLAS MORNING BRIEFING</b>

Good morning! Gold markets are opening.

📋 <b>Today's Focus:</b>
• London session: 7:00–16:00 UTC
• New York session: 12:00–21:00 UTC
• Highest probability: 12:00–16:00 UTC overlap

⚡ ATLAS scans Gold across M1/M5/M15/M30 every 3 minutes.

💡 <b>Reminder:</b> Never risk more than 1-2% per trade.
Set your stop loss BEFORE entering.

Good luck today. — ATLAS
""".strip()
    return send_message(msg)


def send_daily_evening(signals_today: int, wins: int, losses: int):
    """Evening performance summary."""
    wr = round(wins / (wins + losses) * 100, 1) if (wins + losses) > 0 else 0
    verdict = "✅ Good day!" if wr >= 50 else "⚠️ Tough day — review your trades."
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
