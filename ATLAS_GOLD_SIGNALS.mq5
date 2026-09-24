//+------------------------------------------------------------------+
//| ATLAS_GOLD_SIGNALS.mq5                                           |
//| Gold (XAU/USD) confluence signals pushed to Telegram.            |
//| Runs on the MT5 broker feed, so price is live (no Yahoo delay).  |
//| SIGNALS ONLY - this EA never places, modifies or closes orders.  |
//+------------------------------------------------------------------+
#property copyright "ATLAS"
#property version   "2.00"
#property description "Gold signals to Telegram. Signals only, never trades."

//==================================================================
// INPUTS
//==================================================================
input group "Telegram"
input string TG_TOKEN          = "";      // Bot token from @BotFather
input string TG_CHAT_ID        = "";      // Your group / channel / user chat id
input bool   SEND_STARTUP      = true;    // Send a message when the EA starts

input group "Symbols"
input string SYMBOL_OVERRIDE   = "";      // Empty = use the chart symbol (attach to XAUUSD / GOLD#)
input string DXY_SYMBOL        = "";      // Dollar index symbol on your broker (e.g. DXY, USDX). Empty = DXY signal off

input group "Timeframe profiles"
input bool   USE_M1            = false;   // M1 lost money in backtests (PF ~0.85)
input bool   USE_M5            = false;   // M5 lost about -137R over 20 months
input bool   USE_M15           = true;
input bool   USE_M30           = true;

input group "Strategy"
input int    MIN_COUNT         = 3;       // Min agreeing signals (out of 5) to fire
input int    WINDOW_BARS       = 5;       // A signal still counts for this many bars after it fired
input int    COOLDOWN_BARS     = 10;      // Bars to wait after a signal (per timeframe)
input double SL_ATR_MULT       = 1.0;     // Stop loss = ATR x this
input double TP_ATR_MULT       = 3.0;     // Take profit = ATR x this
input double MAX_SPREAD        = 0.0;     // Skip signal if spread > this (price units, e.g. 0.50). 0 = off
input int    TRACK_HOURS       = 24;      // Stop tracking a signal after this many hours (marked EXPIRED)
input int    WARMUP_BARS       = 400;     // History bars replayed at start to build indicator state

input group "News (MT5 economic calendar - live only)"
input bool   NEWS_ENABLED      = true;
input string NEWS_CURRENCY     = "USD";
input int    NEWS_WINDOW_MIN   = 60;      // Add a warning to signals when high-impact news is within this many minutes
input int    NEWS_AFTER_MIN    = 15;      // ...or happened within this many minutes ago
input int    NEWS_PREALERT_MIN = 30;      // Send a standalone heads-up this many minutes before high-impact news (0 = off)
input bool   NEWS_BLOCK        = false;   // true = do not send signals while news is near

//==================================================================
// CONSTANTS  (same values as the original Manual Guide logic)
//==================================================================
#define NPROF 4
#define ATR_LEN 14
#define BRK_LOOKBACK 20
#define BRK_MAX_WAIT 30
#define FAST_LEN 9
#define SLOW_LEN 50
#define DXY_LOOKBACK 8

const double BRK_TOL          = 0.15;
const double EMA_PULLBACK_ATR = 0.3;
const double EMA_CONT_BODY    = 0.4;
const double IMPULSE_BODY     = 1.0;
const double TOUCH_ATR        = 0.2;
const double DXY_IMPULSE      = 1.5;
const double DXY_COMPRESS     = 0.4;
const double DXY_RETRACE_PCT  = 20.0;
const int    DXY_MAX_COILED   = 20;

//==================================================================
// TYPES
//==================================================================
struct Profile
{
   bool            enabled;
   bool            ready;
   string          name;
   ENUM_TIMEFRAMES tf;
   ENUM_TIMEFRAMES emaTf;     // higher TF for the EMA20 pullback signal
   ENUM_TIMEFRAMES momTf;     // higher TF for the SMA50 momentum signal
   ENUM_TIMEFRAMES trendTf;   // higher TF for the SMA20 trend filter
   int             hEma;
   int             hMom;
   int             hTrend;
   datetime        lastBar;   // open time of the last processed CLOSED bar
   datetime        lastBar0;  // open time of the last seen forming bar
   long            barCount;
   long            lastSignalBar;
   long            lastFire[10];   // 0-4 buy signals, 5-9 sell signals
   double          ema9;
   double          ema50;
   bool            emaInit;
   double          brkLevel;
   int             brkDir;
   bool            brkWait;
   int             brkAge;
   int             dxState;
   double          dxStart;
   double          dxExtreme;
   int             dxDir;
   int             dxCoiled;
};

struct SigResult
{
   bool   fire;
   int    dir;        // +1 buy, -1 sell
   int    tier;       // 0 WATCH, 1 MODERATE, 2 STRONG
   int    count;
   double atr;
   int    trend;      // +1 bullish, -1 bearish, 0 flat
   bool   agree[5];   // DXY, EMA pullback, Break/Retest, HTF momentum, EMA9/50
};

struct Trk
{
   int      id;
   int      prof;
   int      dir;
   int      tier;
   double   entry;
   double   sl;
   double   tp;
   datetime t;
};

//==================================================================
// GLOBALS
//==================================================================
Profile g_p[NPROF];
Trk     g_trk[];
string  g_sym       = "";
string  g_dxy       = "";
bool    g_dxyOk     = false;
int     g_digits    = 2;
int     g_nextId    = 1;
string  g_logName   = "";
bool    g_tester    = false;

// stats [profile*3 + tier]
int     g_win[NPROF*3];
int     g_loss[NPROF*3];
int     g_exp[NPROF*3];
double  g_gainR[NPROF*3];
double  g_lossR[NPROF*3];

// news cache
ulong    g_nId[];
datetime g_nT[];
string   g_nName[];
datetime g_newsRefresh = 0;
ulong    g_alerted[];

//==================================================================
// SMALL HELPERS
//==================================================================
string TfName(ENUM_TIMEFRAMES tf)
{
   string s = EnumToString(tf);          // PERIOD_H1
   return StringSubstr(s, 7);
}

string Emo(int codepoint)
{
   // Telegram HTML mode accepts numeric entities, keeps this source file pure ASCII
   return "&#" + IntegerToString(codepoint) + ";";
}

string TierName(int tier)
{
   if(tier >= 2) return "STRONG";
   if(tier == 1) return "MODERATE";
   return "WATCH";
}

string HtmlEsc(string s)
{
   StringReplace(s, "&", "&amp;");
   StringReplace(s, "<", "&lt;");
   StringReplace(s, ">", "&gt;");
   return s;
}

string JsonEsc(string s)
{
   StringReplace(s, "\\", "\\\\");
   StringReplace(s, "\"", "\\\"");
   StringReplace(s, "\r", "");
   StringReplace(s, "\n", "\\n");
   StringReplace(s, "\t", " ");
   return s;
}

string PhtTime(datetime gmt)
{
   return TimeToString(gmt + 8 * 3600, TIME_MINUTES) + " PHT";
}

void LogLine(string line)
{
   int h = FileOpen(g_logName, FILE_READ | FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON, ';');
   if(h == INVALID_HANDLE) return;
   if(FileSize(h) == 0)
      FileWriteString(h, "time_server;event;id;timeframe;tier;dir;entry;sl;tp;result_R\r\n");
   FileSeek(h, 0, SEEK_END);
   FileWriteString(h, line + "\r\n");
   FileClose(h);
}

//==================================================================
// TELEGRAM
//==================================================================
bool SendTelegram(string text)
{
   if(g_tester) return true;                 // WebRequest is not available in the tester
   if(TG_TOKEN == "" || TG_CHAT_ID == "")
   {
      Print("ATLAS: TG_TOKEN / TG_CHAT_ID not set - message not sent");
      return false;
   }

   string url  = "https://api.telegram.org/bot" + TG_TOKEN + "/sendMessage";
   string body = "{\"chat_id\":\"" + TG_CHAT_ID + "\",\"text\":\"" + JsonEsc(text) +
                 "\",\"parse_mode\":\"HTML\",\"disable_web_page_preview\":true}";

   char   post[];
   char   res[];
   string resHeaders;
   int n = StringToCharArray(body, post, 0, WHOLE_ARRAY, CP_UTF8);
   if(n > 0) ArrayResize(post, n - 1);       // drop the trailing null

   for(int attempt = 0; attempt < 2; attempt++)
   {
      ResetLastError();
      int code = WebRequest("POST", url, "Content-Type: application/json\r\n", 5000, post, res, resHeaders);
      if(code == 200) return true;
      if(code == -1)
      {
         int err = GetLastError();
         Print("ATLAS: Telegram WebRequest failed, error ", err,
               " (4014 = add https://api.telegram.org under Tools > Options > Expert Advisors > Allow WebRequest)");
      }
      else
         Print("ATLAS: Telegram HTTP ", code, " ", CharArrayToString(res, 0, 200, CP_UTF8));
      Sleep(500);
   }
   return false;
}

//==================================================================
// HIGHER-TIMEFRAME LOOKUPS (always the last COMPLETED higher-TF bar)
//==================================================================
int HtfShift(ENUM_TIMEFRAMES tf, datetime tc)
{
   int sh = iBarShift(g_sym, tf, tc - 1, false);
   if(sh < 0) return -1;
   datetime ot = iTime(g_sym, tf, sh);
   if(ot == 0) return -1;
   if(ot + PeriodSeconds(tf) > tc) sh++;     // that bar is still forming at time tc
   return sh;
}

bool HtfMa(int handle, ENUM_TIMEFRAMES tf, datetime tc, double &ma, double &cl)
{
   int sh = HtfShift(tf, tc);
   if(sh < 0) return false;
   double b[1];
   if(CopyBuffer(handle, 0, sh, 1, b) != 1) return false;
   if(b[0] == EMPTY_VALUE || b[0] <= 0) return false;
   ma = b[0];
   cl = iClose(g_sym, tf, sh);
   return (cl > 0);
}

double AtrAt(const MqlRates &r[], int s)
{
   double sum = 0;
   for(int k = s; k < s + ATR_LEN; k++)
   {
      double tr = MathMax(r[k].high - r[k].low,
                  MathMax(MathAbs(r[k].high - r[k+1].close),
                          MathAbs(r[k].low  - r[k+1].close)));
      sum += tr;
   }
   return sum / ATR_LEN;
}

//==================================================================
// PROFILE STATE
//==================================================================
void ResetState(Profile &ps)
{
   ps.barCount      = 0;
   ps.lastSignalBar = -100000;
   for(int i = 0; i < 10; i++) ps.lastFire[i] = -100000;
   ps.ema9 = 0; ps.ema50 = 0; ps.emaInit = false;
   ps.brkLevel = 0; ps.brkDir = 0; ps.brkWait = false; ps.brkAge = 0;
   ps.dxState = 0; ps.dxStart = 0; ps.dxExtreme = 0; ps.dxDir = 0; ps.dxCoiled = 0;
}

void SetupProfile(int i, bool en, ENUM_TIMEFRAMES tf, ENUM_TIMEFRAMES emaTf,
                  ENUM_TIMEFRAMES momTf, ENUM_TIMEFRAMES trendTf)
{
   g_p[i].enabled = en;
   g_p[i].ready   = false;
   g_p[i].tf      = tf;
   g_p[i].emaTf   = emaTf;
   g_p[i].momTf   = momTf;
   g_p[i].trendTf = trendTf;
   g_p[i].name    = TfName(tf);
   g_p[i].hEma    = INVALID_HANDLE;
   g_p[i].hMom    = INVALID_HANDLE;
   g_p[i].hTrend  = INVALID_HANDLE;
   g_p[i].lastBar = 0;
   g_p[i].lastBar0 = 0;
   ResetState(g_p[i]);
   if(!en) return;

   g_p[i].hEma   = iMA(g_sym, emaTf,   20, 0, MODE_EMA, PRICE_CLOSE);
   g_p[i].hMom   = iMA(g_sym, momTf,   50, 0, MODE_SMA, PRICE_CLOSE);
   g_p[i].hTrend = iMA(g_sym, trendTf, 20, 0, MODE_SMA, PRICE_CLOSE);
   if(g_p[i].hEma == INVALID_HANDLE || g_p[i].hMom == INVALID_HANDLE || g_p[i].hTrend == INVALID_HANDLE)
   {
      Print("ATLAS: could not create indicators for ", g_p[i].name, " - profile disabled");
      g_p[i].enabled = false;
   }
}

//==================================================================
// CORE: evaluate ONE closed bar (index s in a series-ordered array,
// s = 1 is the most recently closed bar). Updates the profile's state.
//==================================================================
bool ProcessBar(Profile &ps, const MqlRates &r[], int got, int s, SigResult &out)
{
   out.fire = false;
   if(s < 1) return false;
   if(s + BRK_LOOKBACK > got - 1) return false;   // not enough history behind this bar

   datetime tc = r[s].time + PeriodSeconds(ps.tf);   // close time of this bar
   double c = r[s].close, o = r[s].open, h = r[s].high, l = r[s].low;
   double atr = AtrAt(r, s);
   ps.barCount++;

   // ---- EMA 9 / 50 on entry timeframe (incremental) ----
   if(!ps.emaInit) { ps.ema9 = c; ps.ema50 = c; ps.emaInit = true; }
   else
   {
      ps.ema9  += (c - ps.ema9)  * 2.0 / (FAST_LEN + 1);
      ps.ema50 += (c - ps.ema50) * 2.0 / (SLOW_LEN + 1);
   }
   if(atr <= 0) return false;

   // ---- Signal 1: DXY divergence (optional) ----
   bool dxBuy = false, dxSell = false;
   if(g_dxyOk)
   {
      int ds = iBarShift(g_dxy, ps.tf, r[s].time, false);
      if(ds >= 0 && MathAbs((double)((long)iTime(g_dxy, ps.tf, ds) - (long)r[s].time)) <= 2.0 * PeriodSeconds(ps.tf))
      {
         double dc   = iClose(g_dxy, ps.tf, ds);
         double dclb = iClose(g_dxy, ps.tf, ds + DXY_LOOKBACK);
         double dsum = 0; int dcnt = 0;
         for(int k = ds; k < ds + 14; k++)
         {
            double a = iClose(g_dxy, ps.tf, k), b = iClose(g_dxy, ps.tf, k + 1);
            if(a <= 0 || b <= 0) { dcnt = 0; break; }
            dsum += MathAbs(a - b);
            dcnt++;
         }
         double datr = (dcnt == 14) ? dsum / 14.0 : 0.0;
         if(datr > 0 && dc > 0 && dclb > 0)
         {
            double dmove    = dc - dclb;
            double dmoveAtr = dmove / datr;
            double gmoveAtr = (c - r[s + DXY_LOOKBACK].close) / atr;

            if(ps.dxState == 0)
            {
               if(MathAbs(dmoveAtr) >= DXY_IMPULSE && MathAbs(gmoveAtr) <= DXY_COMPRESS)
               {
                  ps.dxState   = 1;
                  ps.dxDir     = (dmove > 0) ? 1 : -1;
                  ps.dxStart   = dclb;
                  ps.dxExtreme = dc;
                  ps.dxCoiled  = 0;
               }
            }
            else
            {
               ps.dxCoiled++;
               if((ps.dxDir > 0 && dc > ps.dxExtreme) || (ps.dxDir < 0 && dc < ps.dxExtreme))
                  ps.dxExtreme = dc;
               double rng = MathAbs(ps.dxExtreme - ps.dxStart);
               double retr = MathAbs(ps.dxExtreme - dc);
               double pct = (rng > 0) ? retr / rng * 100.0 : 0.0;
               if(pct >= DXY_RETRACE_PCT)
               {
                  if(-ps.dxDir > 0) dxBuy = true; else dxSell = true;
                  ps.dxState = 0;
               }
               else if(ps.dxCoiled >= DXY_MAX_COILED)
                  ps.dxState = 0;
            }
         }
      }
   }

   // ---- Signal 2: EMA20 (higher TF) pullback + continuation ----
   double htfEma = 0, htfEmaCl = 0;
   bool haveEma = HtfMa(ps.hEma, ps.emaTf, tc, htfEma, htfEmaCl);
   bool emaBuy = false, emaSell = false;
   if(haveEma)
   {
      emaBuy = (c > htfEma) &&
               (l >= htfEma - EMA_PULLBACK_ATR * atr && l <= htfEma + EMA_PULLBACK_ATR * atr) &&
               (c > o) && ((c - o) >= EMA_CONT_BODY * atr) && (c > r[s+1].high);
      emaSell = (c < htfEma) &&
                (h >= htfEma - EMA_PULLBACK_ATR * atr && h <= htfEma + EMA_PULLBACK_ATR * atr) &&
                (c < o) && ((o - c) >= EMA_CONT_BODY * atr) && (c < r[s+1].low);
   }

   // ---- Signal 3: break of the 20-bar range, then retest ----
   //      (retest is only checked on bars AFTER the breakout bar)
   double rh = r[s+1].high, rl = r[s+1].low;
   for(int k = s + 2; k <= s + BRK_LOOKBACK; k++)
   {
      if(r[k].high > rh) rh = r[k].high;
      if(r[k].low  < rl) rl = r[k].low;
   }
   bool brkBuy = false, brkSell = false;
   if(ps.brkWait)
   {
      ps.brkAge++;
      if(ps.brkDir == 1)
      {
         if(l <= ps.brkLevel + BRK_TOL * atr && c > ps.brkLevel) { brkBuy = true; ps.brkWait = false; }
         else if(c < ps.brkLevel - BRK_TOL * atr) ps.brkWait = false;
      }
      else
      {
         if(h >= ps.brkLevel - BRK_TOL * atr && c < ps.brkLevel) { brkSell = true; ps.brkWait = false; }
         else if(c > ps.brkLevel + BRK_TOL * atr) ps.brkWait = false;
      }
      if(ps.brkWait && ps.brkAge >= BRK_MAX_WAIT) ps.brkWait = false;
   }
   else
   {
      if(c > rh)      { ps.brkLevel = rh; ps.brkDir =  1; ps.brkWait = true; ps.brkAge = 0; }
      else if(c < rl) { ps.brkLevel = rl; ps.brkDir = -1; ps.brkWait = true; ps.brkAge = 0; }
   }

   // ---- Signal 4: higher-TF momentum (close vs SMA50 of higher TF + big body) ----
   double momMa = 0, momCl = 0;
   bool haveMom = HtfMa(ps.hMom, ps.momTf, tc, momMa, momCl);
   double body = c - o;
   bool htfBuy  = haveMom && (c > momMa) && (body  >= IMPULSE_BODY * atr);
   bool htfSell = haveMom && (c < momMa) && (-body >= IMPULSE_BODY * atr);

   // ---- Signal 5: EMA9 touch with EMA9 > EMA50 alignment ----
   double e9 = ps.ema9, e50 = ps.ema50;
   bool touchedUp   = (l >= e9 - TOUCH_ATR * atr && l <= e9 + TOUCH_ATR * atr);
   bool touchedDown = (h >= e9 - TOUCH_ATR * atr && h <= e9 + TOUCH_ATR * atr);
   bool e950Buy  = (e9 > e50) && (c > e50) && touchedUp   && (c > o) && (c > e9);
   bool e950Sell = (e9 < e50) && (c < e50) && touchedDown && (c < o) && (c < e9);

   // ---- record fires, then count what is still inside the window ----
   bool f[10];
   f[0] = dxBuy;  f[1] = emaBuy;  f[2] = brkBuy;  f[3] = htfBuy;  f[4] = e950Buy;
   f[5] = dxSell; f[6] = emaSell; f[7] = brkSell; f[8] = htfSell; f[9] = e950Sell;
   for(int i = 0; i < 10; i++)
      if(f[i]) ps.lastFire[i] = ps.barCount;

   int buyCount = 0, sellCount = 0;
   bool buyOn[5], sellOn[5];
   for(int i = 0; i < 5; i++)
   {
      buyOn[i]  = (ps.barCount - ps.lastFire[i]     <= WINDOW_BARS);
      sellOn[i] = (ps.barCount - ps.lastFire[i + 5] <= WINDOW_BARS);
      if(buyOn[i])  buyCount++;
      if(sellOn[i]) sellCount++;
   }

   // ---- higher-TF trend filter ----
   double tMa = 0, tCl = 0;
   int trend = 0;
   if(HtfMa(ps.hTrend, ps.trendTf, tc, tMa, tCl))
      trend = (tCl > tMa) ? 1 : ((tCl < tMa) ? -1 : 0);

   bool showBuy  = (trend >= 0) && (buyCount  >= MIN_COUNT) && (buyCount >= sellCount);
   bool showSell = (trend <= 0) && (sellCount >= MIN_COUNT) && (sellCount >  buyCount);
   bool cooling  = (ps.barCount - ps.lastSignalBar) <= COOLDOWN_BARS;

   if((showBuy || showSell) && !cooling)
   {
      ps.lastSignalBar = ps.barCount;
      out.fire  = true;
      out.dir   = showBuy ? 1 : -1;
      out.count = showBuy ? buyCount : sellCount;
      out.tier  = (out.count >= 5) ? 2 : ((out.count == 4) ? 1 : 0);
      out.atr   = atr;
      out.trend = trend;
      for(int i = 0; i < 5; i++)
         out.agree[i] = showBuy ? buyOn[i] : sellOn[i];
      return true;
   }
   return false;
}

//==================================================================
// NEWS (MT5 built-in economic calendar; not available in tester)
//==================================================================
void RefreshNews()
{
   if(!NEWS_ENABLED || g_tester) return;
   datetime now = TimeTradeServer();
   if(now - g_newsRefresh < 60) return;
   g_newsRefresh = now;

   int ahead = MathMax(NEWS_WINDOW_MIN, NEWS_PREALERT_MIN) + 5;
   MqlCalendarValue v[];
   ArrayResize(g_nId, 0); ArrayResize(g_nT, 0); ArrayResize(g_nName, 0);
   if(!CalendarValueHistory(v, now - (NEWS_AFTER_MIN + 5) * 60, now + ahead * 60, NULL, NEWS_CURRENCY))
      return;

   for(int i = 0; i < ArraySize(v); i++)
   {
      MqlCalendarEvent ev;
      if(!CalendarEventById(v[i].event_id, ev)) continue;
      if(ev.importance != CALENDAR_IMPORTANCE_HIGH) continue;
      int n = ArraySize(g_nId);
      ArrayResize(g_nId, n + 1); ArrayResize(g_nT, n + 1); ArrayResize(g_nName, n + 1);
      g_nId[n]   = v[i].id;
      g_nT[n]    = v[i].time;
      g_nName[n] = ev.name;
   }
}

// One-line warning for signals ("" when nothing relevant is near)
string NewsLine()
{
   if(!NEWS_ENABLED || g_tester) return "";
   datetime now = TimeTradeServer();
   string out = "";
   for(int i = 0; i < ArraySize(g_nId); i++)
   {
      int mins = (int)MathCeil((double)((long)g_nT[i] - (long)now) / 60.0);
      if(mins > NEWS_WINDOW_MIN || mins < -NEWS_AFTER_MIN) continue;
      string when = (mins >= 0) ? ("in " + IntegerToString(mins) + " min")
                                : (IntegerToString(-mins) + " min ago");
      if(out != "") out += "\n";
      out += Emo(9888) + " <b>High-impact news:</b> " + HtmlEsc(g_nName[i]) + " " + when;
   }
   return out;
}

bool WasAlerted(ulong id)
{
   for(int i = 0; i < ArraySize(g_alerted); i++)
      if(g_alerted[i] == id) return true;
   return false;
}

void SendNewsPrealerts()
{
   if(!NEWS_ENABLED || g_tester || NEWS_PREALERT_MIN <= 0) return;
   datetime now = TimeTradeServer();
   datetime gmtNow = TimeGMT();
   for(int i = 0; i < ArraySize(g_nId); i++)
   {
      int mins = (int)MathCeil((double)((long)g_nT[i] - (long)now) / 60.0);
      if(mins <= 0 || mins > NEWS_PREALERT_MIN) continue;
      if(WasAlerted(g_nId[i])) continue;

      datetime evGmt = (datetime)((long)g_nT[i] + ((long)gmtNow - (long)now));   // server time -> GMT
      string msg = Emo(128240) + " <b>HIGH-IMPACT NEWS in " + IntegerToString(mins) + " min</b>\n" +
                   HtmlEsc(g_nName[i]) + " (" + NEWS_CURRENCY + ")\n" +
                   PhtTime(evGmt) + "\n" +
                   "Gold can whipsaw around this release - be careful with entries.";
      SendTelegram(msg);
      int n = ArraySize(g_alerted);
      ArrayResize(g_alerted, n + 1);
      g_alerted[n] = g_nId[i];
      if(n > 200)   // keep the list small
      {
         ArrayRemove(g_alerted, 0, 100);
      }
   }
}

//==================================================================
// SIGNAL TRACKING (TP / SL follow-ups + stats used by Strategy Tester)
//==================================================================
void RecordStat(int prof, int tier, double R, int kind)   // kind: 0 TP, 1 SL, 2 expired
{
   int ix = prof * 3 + tier;
   if(kind == 0)      g_win[ix]++;
   else if(kind == 1) g_loss[ix]++;
   else               g_exp[ix]++;
   if(R >= 0) g_gainR[ix] += R; else g_lossR[ix] += -R;
}

void CheckOutcomes()
{
   int n = ArraySize(g_trk);
   if(n == 0) return;
   double bid = SymbolInfoDouble(g_sym, SYMBOL_BID);
   double ask = SymbolInfoDouble(g_sym, SYMBOL_ASK);
   if(bid <= 0 || ask <= 0) return;

   for(int i = n - 1; i >= 0; i--)
   {
      Trk t = g_trk[i];
      double risk = MathAbs(t.entry - t.sl);
      int kind = -1;
      double R = 0, exitPx = 0;

      if(t.dir > 0)
      {
         if(bid <= t.sl)      { kind = 1; R = -1.0;  exitPx = t.sl; }
         else if(bid >= t.tp) { kind = 0; R = MathAbs(t.tp - t.entry) / risk; exitPx = t.tp; }
      }
      else
      {
         if(ask >= t.sl)      { kind = 1; R = -1.0;  exitPx = t.sl; }
         else if(ask <= t.tp) { kind = 0; R = MathAbs(t.tp - t.entry) / risk; exitPx = t.tp; }
      }

      if(kind < 0 && ((long)TimeCurrent() - (long)t.t) >= (long)TRACK_HOURS * 3600)
      {
         exitPx = (t.dir > 0) ? bid : ask;
         R = (risk > 0) ? t.dir * (exitPx - t.entry) / risk : 0;
         kind = 2;
      }
      if(kind < 0) continue;

      RecordStat(t.prof, t.tier, R, kind);
      string tfn = g_p[t.prof].name;
      string dirS = (t.dir > 0) ? "BUY" : "SELL";
      int mins = (int)((TimeCurrent() - t.t) / 60);

      string head;
      if(kind == 0)      head = Emo(9989)  + " <b>TP HIT</b>";
      else if(kind == 1) head = Emo(10060) + " <b>SL HIT</b>";
      else               head = Emo(9203)  + " <b>EXPIRED</b>";

      string msg = head + "  #" + IntegerToString(t.id) + "\n" +
                   "XAU/USD " + tfn + " " + dirS + " (" + TierName(t.tier) + ")\n" +
                   "Entry " + DoubleToString(t.entry, g_digits) + " -> " + DoubleToString(exitPx, g_digits) +
                   "  |  " + (R >= 0 ? "+" : "") + DoubleToString(R, 2) + "R  |  " + IntegerToString(mins) + " min";
      SendTelegram(msg);

      string evn = (kind == 0) ? "TP" : ((kind == 1) ? "SL" : "EXPIRED");
      LogLine(TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS) + ";" + evn + ";" + IntegerToString(t.id) + ";" +
              tfn + ";" + TierName(t.tier) + ";" + dirS + ";" + DoubleToString(t.entry, g_digits) + ";" +
              DoubleToString(t.sl, g_digits) + ";" + DoubleToString(t.tp, g_digits) + ";" + DoubleToString(R, 2));

      // remove from list
      for(int j = i; j < n - 1; j++) g_trk[j] = g_trk[j + 1];
      n--;
      ArrayResize(g_trk, n);
   }
}

//==================================================================
// EMIT A SIGNAL
//==================================================================
void EmitSignal(Profile &ps, int pIdx, SigResult &res, datetime barOpen)
{
   // do not alert on stale bars (e.g. EA restarted after the weekend)
   if((long)TimeCurrent() - ((long)barOpen + PeriodSeconds(ps.tf)) > 2 * (long)PeriodSeconds(ps.tf)) return;

   double bid = SymbolInfoDouble(g_sym, SYMBOL_BID);
   double ask = SymbolInfoDouble(g_sym, SYMBOL_ASK);
   if(bid <= 0 || ask <= 0) return;
   double spread = ask - bid;

   if(MAX_SPREAD > 0 && spread > MAX_SPREAD)
   {
      Print("ATLAS: ", ps.name, " signal skipped - spread ", DoubleToString(spread, g_digits), " > ", DoubleToString(MAX_SPREAD, g_digits));
      return;
   }

   string news = NewsLine();
   if(NEWS_BLOCK && news != "")
   {
      Print("ATLAS: ", ps.name, " signal skipped - high-impact news near");
      return;
   }

   double entry = (res.dir > 0) ? ask : bid;             // live broker price
   double sl    = entry - res.dir * SL_ATR_MULT * res.atr;
   double tp    = entry + res.dir * TP_ATR_MULT * res.atr;
   entry = NormalizeDouble(entry, g_digits);
   sl    = NormalizeDouble(sl, g_digits);
   tp    = NormalizeDouble(tp, g_digits);
   double risk = MathAbs(entry - sl);

   int id = g_nextId++;
   if(!g_tester) GlobalVariableSet("ATLAS_GOLD_NEXT_ID", g_nextId);

   // track it
   int n = ArraySize(g_trk);
   ArrayResize(g_trk, n + 1);
   g_trk[n].id = id; g_trk[n].prof = pIdx; g_trk[n].dir = res.dir; g_trk[n].tier = res.tier;
   g_trk[n].entry = entry; g_trk[n].sl = sl; g_trk[n].tp = tp; g_trk[n].t = TimeCurrent();

   string dirS = (res.dir > 0) ? "BUY" : "SELL";
   LogLine(TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS) + ";SIGNAL;" + IntegerToString(id) + ";" + ps.name + ";" +
           TierName(res.tier) + ";" + dirS + ";" + DoubleToString(entry, g_digits) + ";" +
           DoubleToString(sl, g_digits) + ";" + DoubleToString(tp, g_digits) + ";");

   int nSig = g_dxyOk ? 5 : 4;
   string trendS = (res.trend > 0) ? "BULLISH" : ((res.trend < 0) ? "BEARISH" : "FLAT");
   string ok = Emo(10003), no = Emo(10007);

   string m = "";
   m += Emo(res.dir > 0 ? 128994 : 128308) + " <b>ATLAS GOLD - " + dirS + "</b>  #" + IntegerToString(id) + "\n";
   m += "<b>XAU/USD " + ps.name + "</b> | " + TierName(res.tier) + " (" + IntegerToString(res.count) + "/" + IntegerToString(nSig) + ")\n\n";
   m += Emo(128176) + " <b>Entry (live):</b> <code>" + DoubleToString(entry, g_digits) + "</code>\n";
   m += Emo(128721) + " <b>Stop Loss:</b> <code>" + DoubleToString(sl, g_digits) + "</code> (" + DoubleToString(risk, g_digits) + ")\n";
   m += Emo(127919) + " <b>Take Profit:</b> <code>" + DoubleToString(tp, g_digits) + "</code> (RR 1:" + DoubleToString(TP_ATR_MULT / SL_ATR_MULT, 1) + ")\n";
   m += "Spread: " + DoubleToString(spread, g_digits) + "\n\n";
   m += Emo(128202) + " Trend (" + TfName(ps.trendTf) + "): " + trendS + "\n";
   m += "Confluence: DXY " + (g_dxyOk ? (res.agree[0] ? ok : no) : "-") +
        " | EMA pullback " + (res.agree[1] ? ok : no) +
        " | Break/Retest " + (res.agree[2] ? ok : no) +
        " | HTF momentum " + (res.agree[3] ? ok : no) +
        " | EMA9/50 " + (res.agree[4] ? ok : no) + "\n";
   if(risk > 0 && spread / risk > 0.2)
      m += Emo(9888) + " Spread is " + IntegerToString((int)(spread / risk * 100)) + "% of the stop distance\n";
   if(news != "") m += "\n" + news + "\n";
   m += "\n" + Emo(9200) + " " + PhtTime(TimeGMT()) + "\n";
   m += "<i>Signal only - apply your own TA before entering.</i>";

   Print("ATLAS: ", dirS, " ", ps.name, " ", TierName(res.tier), " entry ", DoubleToString(entry, g_digits),
         " sl ", DoubleToString(sl, g_digits), " tp ", DoubleToString(tp, g_digits));
   SendTelegram(m);
}

//==================================================================
// ADVANCE ONE PROFILE (warm-up on first run, then bar by bar)
//==================================================================
void Advance(int pIdx)
{
   // NOTE: always work on the global element g_p[pIdx] directly (a struct copy would lose state)
   datetime t0 = iTime(g_sym, g_p[pIdx].tf, 0);
   if(t0 == 0) return;
   if(g_p[pIdx].ready && t0 == g_p[pIdx].lastBar0) return;   // no new bar yet

   int need = g_p[pIdx].ready ? 150 : WARMUP_BARS + 60;
   MqlRates r[];
   ArraySetAsSeries(r, true);
   int got = CopyRates(g_sym, g_p[pIdx].tf, 0, need, r);
   if(got < BRK_LOOKBACK + 30) return;

   if(!g_p[pIdx].ready)
   {
      if(BarsCalculated(g_p[pIdx].hEma) <= 0 || BarsCalculated(g_p[pIdx].hMom) <= 0 ||
         BarsCalculated(g_p[pIdx].hTrend) <= 0)
         return;   // indicators not ready yet - try again on the next call

      ResetState(g_p[pIdx]);
      SigResult tmp;
      for(int s = got - 1 - BRK_LOOKBACK; s >= 1; s--)
         ProcessBar(g_p[pIdx], r, got, s, tmp);            // warm-up only, nothing is sent
      g_p[pIdx].lastBar  = r[1].time;
      g_p[pIdx].lastBar0 = t0;
      g_p[pIdx].ready    = true;
      Print("ATLAS: ", g_p[pIdx].name, " profile ready (", got, " bars replayed)");
      return;
   }

   g_p[pIdx].lastBar0 = t0;
   int newCnt = 0;
   for(int k = 1; k < got; k++)
   {
      if(r[k].time > g_p[pIdx].lastBar) newCnt++;
      else break;
   }
   if(newCnt == 0) return;
   if(newCnt > 100) { g_p[pIdx].ready = false; return; }   // long gap: rebuild state next call

   for(int s = newCnt; s >= 1; s--)
   {
      SigResult res;
      bool fired = ProcessBar(g_p[pIdx], r, got, s, res);
      if(fired && res.fire && s == 1)
         EmitSignal(g_p[pIdx], pIdx, res, r[1].time);
   }
   g_p[pIdx].lastBar = r[1].time;
}

void Run()
{
   for(int i = 0; i < NPROF; i++)
      if(g_p[i].enabled) Advance(i);
   CheckOutcomes();
}

//==================================================================
// STATS
//==================================================================
double TotalR()
{
   double t = 0;
   for(int i = 0; i < NPROF * 3; i++) t += g_gainR[i] - g_lossR[i];
   return t;
}

void PrintStats()
{
   Print("================ ATLAS GOLD SIGNALS - RESULTS ================");
   Print("Outcome per signal: TP = +", DoubleToString(TP_ATR_MULT / SL_ATR_MULT, 2), "R, SL = -1R (entry at ask/bid, so spread is included)");
   double allGain = 0, allLoss = 0; int allW = 0, allL = 0, allE = 0;
   for(int p = 0; p < NPROF; p++)
   {
      if(!g_p[p].enabled) continue;
      for(int t = 0; t < 3; t++)
      {
         int ix = p * 3 + t;
         int n = g_win[ix] + g_loss[ix] + g_exp[ix];
         if(n == 0) continue;
         double wr = (g_win[ix] + g_loss[ix] > 0) ? 100.0 * g_win[ix] / (g_win[ix] + g_loss[ix]) : 0;
         double pf = (g_lossR[ix] > 0) ? g_gainR[ix] / g_lossR[ix] : 0;
         Print(StringFormat("%-4s %-8s n=%d  TP=%d SL=%d EXP=%d  winrate=%.1f%%  netR=%+.2f  PF=%.2f",
               g_p[p].name, TierName(t), n, g_win[ix], g_loss[ix], g_exp[ix], wr, g_gainR[ix] - g_lossR[ix], pf));
         allGain += g_gainR[ix]; allLoss += g_lossR[ix];
         allW += g_win[ix]; allL += g_loss[ix]; allE += g_exp[ix];
      }
   }
   int allN = allW + allL + allE;
   double allWr = (allW + allL > 0) ? 100.0 * allW / (allW + allL) : 0;
   double allPf = (allLoss > 0) ? allGain / allLoss : 0;
   Print(StringFormat("ALL  n=%d  TP=%d SL=%d EXP=%d  winrate=%.1f%%  netR=%+.2f  PF=%.2f  (still open: %d)",
         allN, allW, allL, allE, allWr, allGain - allLoss, allPf, ArraySize(g_trk)));
   double be = 100.0 / (1.0 + TP_ATR_MULT / SL_ATR_MULT);
   Print(StringFormat("Break-even win rate at this RR is %.1f%%. Signal log: Common\\Files\\%s", be, g_logName));
   Print("==============================================================");
}

//==================================================================
// EVENTS
//==================================================================
int OnInit()
{
   g_tester = (bool)MQLInfoInteger(MQL_TESTER);
   g_sym    = (SYMBOL_OVERRIDE == "") ? _Symbol : SYMBOL_OVERRIDE;
   if(!SymbolSelect(g_sym, true))
   {
      Print("ATLAS: symbol ", g_sym, " not found in Market Watch");
      return INIT_FAILED;
   }
   g_digits = (int)SymbolInfoInteger(g_sym, SYMBOL_DIGITS);

   g_dxyOk = false;
   if(DXY_SYMBOL != "")
   {
      if(SymbolSelect(DXY_SYMBOL, true)) { g_dxy = DXY_SYMBOL; g_dxyOk = true; }
      else Print("ATLAS: DXY symbol '", DXY_SYMBOL, "' not found - DXY signal disabled");
   }

   if(!g_tester && (TG_TOKEN == "" || TG_CHAT_ID == ""))
      Alert("ATLAS Gold Signals: fill in TG_TOKEN and TG_CHAT_ID in the EA inputs.");

   g_logName = (g_tester ? "tester_" : "") + "atlas_gold_signals.csv";

   SetupProfile(0, USE_M1,  PERIOD_M1,  PERIOD_M5,  PERIOD_M15, PERIOD_M15);
   SetupProfile(1, USE_M5,  PERIOD_M5,  PERIOD_M15, PERIOD_H1,  PERIOD_H1);
   SetupProfile(2, USE_M15, PERIOD_M15, PERIOD_H1,  PERIOD_D1,  PERIOD_D1);
   SetupProfile(3, USE_M30, PERIOD_M30, PERIOD_H1,  PERIOD_D1,  PERIOD_D1);

   ArrayInitialize(g_win, 0); ArrayInitialize(g_loss, 0); ArrayInitialize(g_exp, 0);
   ArrayInitialize(g_gainR, 0.0); ArrayInitialize(g_lossR, 0.0);

   if(!g_tester && GlobalVariableCheck("ATLAS_GOLD_NEXT_ID"))
      g_nextId = (int)GlobalVariableGet("ATLAS_GOLD_NEXT_ID");

   EventSetTimer(1);

   if(SEND_STARTUP && !g_tester)
   {
      string tfs = "";
      for(int i = 0; i < NPROF; i++)
         if(g_p[i].enabled) tfs += (tfs == "" ? "" : ", ") + g_p[i].name;
      string m = Emo(9989) + " <b>ATLAS Gold Signals online</b>\n" +
                 "Symbol: " + g_sym + " | Timeframes: " + tfs + "\n" +
                 "Feed: " + AccountInfoString(ACCOUNT_SERVER) + "\n" +
                 "DXY signal: " + (g_dxyOk ? "on" : "off") + " | News warnings: " + (NEWS_ENABLED ? "on" : "off");
      SendTelegram(m);
   }
   Print("ATLAS Gold Signals started on ", g_sym, " (DXY ", (g_dxyOk ? g_dxy : "off"), ")");
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   for(int i = 0; i < NPROF; i++)
   {
      if(g_p[i].hEma   != INVALID_HANDLE) IndicatorRelease(g_p[i].hEma);
      if(g_p[i].hMom   != INVALID_HANDLE) IndicatorRelease(g_p[i].hMom);
      if(g_p[i].hTrend != INVALID_HANDLE) IndicatorRelease(g_p[i].hTrend);
   }
   if(g_tester) PrintStats();
}

void OnTick()
{
   Run();
}

void OnTimer()
{
   Run();
   RefreshNews();
   SendNewsPrealerts();
}

double OnTester()
{
   return TotalR();
}
//+------------------------------------------------------------------+
