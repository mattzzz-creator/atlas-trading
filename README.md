# ATLAS — Trading Signal System

## Setup & Deploy to Railway (Free)

### Step 1 — Get your Telegram Bot

1. Open Telegram → search **@BotFather**
2. Send `/newbot` → name it "ATLAS Signals"
3. Copy the **bot token** it gives you
4. Add the bot to your trading group
5. Get your group's chat ID:
   - Send a message in the group
   - Go to: `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
   - Find `"chat":{"id":` — that number is your chat ID

### Step 2 — Deploy to Railway

1. Go to **railway.app** → sign up free
2. Click **New Project** → **Deploy from GitHub**
3. Upload this folder to a new GitHub repo first, then connect
   OR use **Railway CLI**: `railway up`
4. Set environment variables in Railway dashboard:
   ```
   TWELVE_DATA_API_KEY=your_key
   TELEGRAM_BOT_TOKEN=your_bot_token
   TELEGRAM_CHAT_ID=your_chat_id
   ```
5. Railway gives you a URL like `atlas-production.up.railway.app`
6. Share that URL with your brothers — works on any device!

### Step 3 — Local testing first

```bash
# Backend
cd backend
pip install -r requirements.txt
cp ../.env.example .env  # fill in your keys
python -m uvicorn server:app --reload --port 8000

# Frontend (new terminal)
cd frontend
npm install
npm run dev
# Open http://localhost:3001
```

### Markets Covered
- 💱 Forex: XAU/USD, EUR/USD, GBP/JPY
- 📈 Stocks: S&P 500, Nasdaq
- ₿ Crypto: BTC/USDT, ETH/USDT (Binance — no key needed)

### How signals work
- Auto-scans every 5 minutes
- Signals with 65%+ confidence sent to Telegram automatically
- Morning briefing at 6:45 AM UTC (before London open)
- Evening report at 9:00 PM UTC (after NY close)
