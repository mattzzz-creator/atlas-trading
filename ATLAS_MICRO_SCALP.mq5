//+------------------------------------------------------------------+
//| ATLAS_MICRO_SCALP.mq5                                            |
//| 1-minute micro liquidity sweep + Fair Value Gap scalp.           |
//| VIRTUAL trades only: the EA simulates limit orders, fills, SL,   |
//| TP, time exits and the risk rules, then reports the results.     |
//| It never places, modifies or closes real orders.                 |
//| Use it in the Strategy Tester (Every tick based on real ticks)   |
//| to measure the strategy on your broker's real bid/ask.           |
//+------------------------------------------------------------------+
#property copyright "ATLAS"
#property version   "1.00"
#property description "1m sweep + FVG scalp. Virtual trades only, never trades."

//==================================================================
// INPUTS
//==================================================================
input group "Setup (1-minute chart data)"
input int    LOOKBACK         = 8;      // Micro range = previous N candles (5-10)
input double SWEEP_MIN        = 0.0;    // Min sweep depth in PRICE units. 0 = preset (gold 0.50, forex 3 pips, index 5)
input double SWEEP_MAX        = 0.0;    // Max sweep depth in PRICE units. 0 = preset (gold 1.50, forex 6 pips, index 15)
input double SL_PAD           = 0.0;    // Stop beyond sweep extreme, PRICE units. 0 = preset (gold 1.00, forex 5 pips, index 10)
input double DISP_MIN_ATR     = 0.7;    // Displacement candle body must be >= this x ATR(14)
input double FVG_MIN_ATR      = 0.05;   // Fair value gap must be >= this x ATR(14)
input bool   ENTRY_MIDPOINT   = true;   // true = limit at gap midpoint, false = at gap boundary
input double MAX_RISK_ATR     = 4.0;    // Skip if stop distance > this x ATR(14)
input double MAX_SPREAD_RISK  = 0.25;   // Skip if spread > this fraction of stop distance
input int    SETUP_COOLDOWN   = 3;      // Minutes to wait after a setup before taking another

input group "Exits"
input double RR               = 1.1;    // Take profit = stop distance x RR
input int    EXPIRY_BARS      = 3;      // Cancel the limit order if not filled within N minutes
input int    MAX_HOLD_MIN     = 8;      // Close at market this many minutes after the fill

input group "Risk protocol (virtual account)"
input double START_EQUITY     = 10000;  // Starting virtual equity, USD
input double RISK_PCT         = 0.25;   // Risk per trade, % of equity
input double DAILY_LOSS_PCT   = 2.0;    // Stop new trades for the day at this loss
input int    MAX_OPEN         = 2;      // Max pending + open positions at once
input int    PAUSE_LOSSES     = 3;      // This many losses in a row...
input int    PAUSE_WINDOW_MIN = 60;     // ...within this many minutes...
input int    PAUSE_MIN        = 30;     // ...pauses new trades for this many minutes

input group "Costs (spread comes from the real bid/ask automatically)"
input double COMM_RT_PER_LOT  = 0.0;    // Commission per 1.0 lot, round turn, USD (XM standard = 0, raw/ECN ~ 7)
input double SLIP_OVERRIDE    = -1;     // Extra slippage on stop-loss exits, PRICE units. -1 = preset

input group "Sessions (UTC, hhmm)"
input bool   USE_SESSIONS     = true;
input int    LON_START        = 700;
input int    LON_END          = 1000;
input int    NY_START         = 1230;
input int    NY_END           = 1600;

input group "Telegram alerts (optional, live only)"
input bool   SEND_TELEGRAM    = false;
input string TG_TOKEN         = "";
input string TG_CHAT_ID       = "";
input bool   WRITE_LOG        = true;   // Write every trade to Common\Files\micro_scalp_<symbol>.csv

//==================================================================
// TYPES / GLOBALS
//==================================================================
#define ATR_LEN 14

struct Ord
{
   int      id;
   int      dir;        // +1 buy, -1 sell
   int      state;      // 0 pending limit, 1 filled/open
   int      sess;       // 0 London, 1 NY, 2 other
   double   entry;
   double   sl;
   double   tp;
   double   riskDist;
   double   riskUSD;
   double   commUSD;
   datetime placed;
   datetime expire;
   datetime filled;
};

Ord      g_ord[];
string   g_sym = "";
int      g_digits = 2;
double   g_pip = 0.0;
double   g_sMin = 0, g_sMax = 0, g_pad = 0, g_slip = 0;
double   g_vpu = 0;            // USD value of a 1.0 price move per 1.0 lot
bool     g_tester = false;
int      g_nextId = 1;
datetime g_lastBar0 = 0;
datetime g_lastSetup = 0;
string   g_logName = "";

// virtual account
double   g_eq = 0, g_dayStartEq = 0, g_peak = 0, g_maxDD = 0;
long     g_day = -1;
bool     g_halt = false;
datetime g_pauseUntil = 0;
datetime g_lossT[10];
int      g_lossN = 0;

// statistics
int      g_placed = 0, g_filled = 0, g_expNoFill = 0, g_missed = 0, g_skipSpread = 0, g_skipRisk = 0;
int      g_cTP = 0, g_cSL = 0, g_cTime = 0, g_wins = 0, g_days = 0, g_haltDays = 0, g_pauses = 0, g_belowMinLot = 0;
double   g_grossWin = 0, g_grossLoss = 0, g_sumR = 0, g_sumCostR = 0, g_sumRisk = 0, g_sumSpreadR = 0;
int      g_sN[3], g_sW[3];
double   g_sR[3];
int      g_dirN[2], g_dirW[2];
double   g_dirR[2];

//==================================================================
// HELPERS
//==================================================================
int Hm(int hhmm) { return (hhmm / 100) * 60 + (hhmm % 100); }

int SessionNow()
{
   MqlDateTime d;
   TimeToStruct(TimeGMT(), d);
   int m = d.hour * 60 + d.min;
   if(m >= Hm(LON_START) && m < Hm(LON_END)) return 0;
   if(m >= Hm(NY_START)  && m < Hm(NY_END))  return 1;
   return 2;
}

string SessName(int s) { return (s == 0) ? "London" : ((s == 1) ? "NewYork" : "Other"); }

string JsonEsc(string s)
{
   StringReplace(s, "\\", "\\\\");
   StringReplace(s, "\"", "\\\"");
   StringReplace(s, "\r", "");
   StringReplace(s, "\n", "\\n");
   return s;
}

bool SendTelegram(string text)
{
   if(g_tester || !SEND_TELEGRAM) return true;
   if(TG_TOKEN == "" || TG_CHAT_ID == "") return false;
   string url  = "https://api.telegram.org/bot" + TG_TOKEN + "/sendMessage";
   string body = "{\"chat_id\":\"" + TG_CHAT_ID + "\",\"text\":\"" + JsonEsc(text) + "\"}";
   char post[]; char res[]; string rh;
   int n = StringToCharArray(body, post, 0, WHOLE_ARRAY, CP_UTF8);
   if(n > 0) ArrayResize(post, n - 1);
   ResetLastError();
   int code = WebRequest("POST", url, "Content-Type: application/json\r\n", 5000, post, res, rh);
   if(code != 200) Print("MICRO: Telegram failed code ", code, " err ", GetLastError());
   return (code == 200);
}

void LogLine(string line)
{
   if(!WRITE_LOG) return;
   int h = FileOpen(g_logName, FILE_READ | FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON, ';');
   if(h == INVALID_HANDLE) return;
   if(FileSize(h) == 0)
      FileWriteString(h, "time_server;id;session;dir;entry;sl;tp;exit;reason;gross_R;cost_R;net_R;pnl_usd;equity\r\n");
   FileSeek(h, 0, SEEK_END);
   FileWriteString(h, line + "\r\n");
   FileClose(h);
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

void InitAsset()
{
   string u = g_sym;
   StringToUpper(u);
   double point = SymbolInfoDouble(g_sym, SYMBOL_POINT);
   g_digits = (int)SymbolInfoInteger(g_sym, SYMBOL_DIGITS);
   g_pip = point * ((g_digits == 5 || g_digits == 3) ? 10.0 : 1.0);

   if(StringFind(u, "XAU") >= 0 || StringFind(u, "GOLD") >= 0)
   { g_sMin = 0.50; g_sMax = 1.50; g_pad = 1.00; g_slip = 0.10; }
   else if(StringFind(u, "US30") >= 0 || StringFind(u, "DJ30") >= 0 || StringFind(u, "WS30") >= 0 || StringFind(u, "DOW") >= 0)
   { g_sMin = 5.0; g_sMax = 15.0; g_pad = 10.0; g_slip = 1.0; }
   else
   { g_sMin = 3 * g_pip; g_sMax = 6 * g_pip; g_pad = 5 * g_pip; g_slip = 0.2 * g_pip; }

   if(SWEEP_MIN > 0)     g_sMin = SWEEP_MIN;
   if(SWEEP_MAX > 0)     g_sMax = SWEEP_MAX;
   if(SL_PAD > 0)        g_pad  = SL_PAD;
   if(SLIP_OVERRIDE >= 0) g_slip = SLIP_OVERRIDE;

   double tv = SymbolInfoDouble(g_sym, SYMBOL_TRADE_TICK_VALUE);
   double ts = SymbolInfoDouble(g_sym, SYMBOL_TRADE_TICK_SIZE);
   g_vpu = (ts > 0) ? tv / ts : 0;
}

void CheckDay()
{
   long day = (long)TimeCurrent() / 86400;
   if(day != g_day)
   {
      g_day = day;
      g_dayStartEq = g_eq;
      g_halt = false;
      g_days++;
   }
}

//==================================================================
// SETUP DETECTION  (C1 = r[3], C2 = r[2] displacement, C3 = r[1] latest closed)
//==================================================================
bool BullSetup(const MqlRates &r[], double atr, double &entry, double &sl)
{
   double body = r[2].close - r[2].open;
   if(body < DISP_MIN_ATR * atr) return false;
   double gap = r[1].low - r[3].high;                       // bullish FVG: C1 high < C3 low
   if(gap <= 0 || gap < FVG_MIN_ATR * atr) return false;

   bool swept = false;
   double microLow = 0;
   for(int X = 2; X <= 3 && !swept; X++)                    // sweep on C2 or on C1
   {
      double ml = r[X + 1].low;
      for(int k = X + 2; k <= X + LOOKBACK; k++)
         if(r[k].low < ml) ml = r[k].low;
      double depth = ml - r[X].low;
      if(depth >= g_sMin && depth <= g_sMax) { swept = true; microLow = ml; }
   }
   if(!swept) return false;
   if(r[2].close <= microLow || r[1].close <= microLow) return false;   // closed back inside the range

   double ext = MathMin(r[3].low, r[2].low);                // extreme sweep wick
   sl    = ext - g_pad;
   entry = ENTRY_MIDPOINT ? (r[3].high + gap / 2.0) : r[1].low;
   return (entry > sl);
}

bool BearSetup(const MqlRates &r[], double atr, double &entry, double &sl)
{
   double body = r[2].open - r[2].close;
   if(body < DISP_MIN_ATR * atr) return false;
   double gap = r[3].low - r[1].high;                       // bearish FVG: C1 low > C3 high
   if(gap <= 0 || gap < FVG_MIN_ATR * atr) return false;

   bool swept = false;
   double microHigh = 0;
   for(int X = 2; X <= 3 && !swept; X++)
   {
      double mh = r[X + 1].high;
      for(int k = X + 2; k <= X + LOOKBACK; k++)
         if(r[k].high > mh) mh = r[k].high;
      double depth = r[X].high - mh;
      if(depth >= g_sMin && depth <= g_sMax) { swept = true; microHigh = mh; }
   }
   if(!swept) return false;
   if(r[2].close >= microHigh || r[1].close >= microHigh) return false;

   double ext = MathMax(r[3].high, r[2].high);
   sl    = ext + g_pad;
   entry = ENTRY_MIDPOINT ? (r[1].high + gap / 2.0) : r[1].high;
   return (sl > entry);
}

//==================================================================
// NEW BAR: look for a setup and place a virtual limit order
//==================================================================
void OnNewBar()
{
   CheckDay();
   if(g_halt) return;
   if(TimeCurrent() < g_pauseUntil) return;

   int sess = SessionNow();
   if(USE_SESSIONS && sess == 2) return;
   if(ArraySize(g_ord) >= MAX_OPEN) return;
   if((long)TimeCurrent() - (long)g_lastSetup < SETUP_COOLDOWN * 60) return;

   MqlRates r[];
   ArraySetAsSeries(r, true);
   int need = LOOKBACK + ATR_LEN + 8;
   int got = CopyRates(g_sym, PERIOD_M1, 0, need, r);
   if(got < need) return;

   double atr = AtrAt(r, 1);
   if(atr <= 0) return;

   double entryB, slB, entryS, slS;
   bool bull = BullSetup(r, atr, entryB, slB);
   bool bear = BearSetup(r, atr, entryS, slS);
   if(bull == bear) return;                                 // none, or conflicting

   int dir = bull ? 1 : -1;
   double entry = bull ? entryB : entryS;
   double sl    = bull ? slB : slS;
   double risk  = MathAbs(entry - sl);
   if(risk <= 0 || risk > MAX_RISK_ATR * atr) { g_skipRisk++; return; }

   double bid = SymbolInfoDouble(g_sym, SYMBOL_BID);
   double ask = SymbolInfoDouble(g_sym, SYMBOL_ASK);
   if(bid <= 0 || ask <= 0) return;
   double spread = ask - bid;
   if(spread > MAX_SPREAD_RISK * risk) { g_skipSpread++; return; }

   double tp = entry + dir * RR * risk;
   entry = NormalizeDouble(entry, g_digits);
   sl    = NormalizeDouble(sl, g_digits);
   tp    = NormalizeDouble(tp, g_digits);

   double riskUSD = g_eq * RISK_PCT / 100.0;
   double lots = (g_vpu > 0) ? riskUSD / (risk * g_vpu) : 0;
   double minLot = SymbolInfoDouble(g_sym, SYMBOL_VOLUME_MIN);
   if(lots < minLot) g_belowMinLot++;

   int n = ArraySize(g_ord);
   ArrayResize(g_ord, n + 1);
   g_ord[n].id       = g_nextId++;
   g_ord[n].dir      = dir;
   g_ord[n].state    = 0;
   g_ord[n].sess     = sess;
   g_ord[n].entry    = entry;
   g_ord[n].sl       = sl;
   g_ord[n].tp       = tp;
   g_ord[n].riskDist = risk;
   g_ord[n].riskUSD  = riskUSD;
   g_ord[n].commUSD  = lots * COMM_RT_PER_LOT;
   g_ord[n].placed   = TimeCurrent();
   g_ord[n].expire   = TimeCurrent() + EXPIRY_BARS * 60;
   g_ord[n].filled   = 0;
   g_lastSetup = TimeCurrent();
   g_placed++;
   g_sumSpreadR += spread / risk;

   SendTelegram(StringFormat("MICRO SCALP %s LIMIT %s @ %s | SL %s | TP %s | valid %d min | risk $%.0f",
                dir > 0 ? "BUY" : "SELL", g_sym, DoubleToString(entry, g_digits),
                DoubleToString(sl, g_digits), DoubleToString(tp, g_digits), EXPIRY_BARS, riskUSD));
}

//==================================================================
// TRADE LIFECYCLE
//==================================================================
void RemoveOrd(int i)
{
   int n = ArraySize(g_ord);
   for(int j = i; j < n - 1; j++) g_ord[j] = g_ord[j + 1];
   ArrayResize(g_ord, n - 1);
}

void CloseTrade(int i, double exitPx, double grossR, int reason)   // reason 0 TP, 1 SL, 2 time
{
   Ord o = g_ord[i];
   double costR = (o.riskUSD > 0) ? o.commUSD / o.riskUSD : 0;
   double netR  = grossR - costR;
   double pnl   = netR * o.riskUSD;

   g_eq += pnl;
   if(g_eq > g_peak) g_peak = g_eq;
   if(g_peak - g_eq > g_maxDD) g_maxDD = g_peak - g_eq;

   if(reason == 0) g_cTP++; else if(reason == 1) g_cSL++; else g_cTime++;
   g_sumR += netR; g_sumCostR += costR; g_sumRisk += o.riskDist;
   if(pnl > 0) { g_wins++; g_grossWin += pnl; } else g_grossLoss += -pnl;
   g_sN[o.sess]++; g_sR[o.sess] += netR; if(pnl > 0) g_sW[o.sess]++;
   int di = (o.dir > 0) ? 0 : 1;
   g_dirN[di]++; g_dirR[di] += netR; if(pnl > 0) g_dirW[di]++;

   // consecutive-loss pause
   if(pnl < 0)
   {
      if(g_lossN < 10) { g_lossT[g_lossN] = TimeCurrent(); g_lossN++; }
      if(g_lossN >= PAUSE_LOSSES)
      {
         int first = g_lossN - PAUSE_LOSSES;
         if((long)g_lossT[g_lossN - 1] - (long)g_lossT[first] <= PAUSE_WINDOW_MIN * 60)
         {
            g_pauseUntil = TimeCurrent() + PAUSE_MIN * 60;
            g_pauses++;
            g_lossN = 0;
         }
         else
         {
            for(int k = 1; k < g_lossN; k++) g_lossT[k - 1] = g_lossT[k];   // slide the window
            g_lossN--;
         }
      }
   }
   else g_lossN = 0;

   // daily circuit breaker
   if(!g_halt && (g_eq - g_dayStartEq) <= -DAILY_LOSS_PCT / 100.0 * g_dayStartEq)
   {
      g_halt = true;
      g_haltDays++;
   }

   string rs = (reason == 0) ? "TP" : ((reason == 1) ? "SL" : "TIME");
   LogLine(TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS) + ";" + IntegerToString(o.id) + ";" + SessName(o.sess) + ";" +
           (o.dir > 0 ? "BUY" : "SELL") + ";" + DoubleToString(o.entry, g_digits) + ";" + DoubleToString(o.sl, g_digits) + ";" +
           DoubleToString(o.tp, g_digits) + ";" + DoubleToString(exitPx, g_digits) + ";" + rs + ";" +
           DoubleToString(grossR, 2) + ";" + DoubleToString(costR, 2) + ";" + DoubleToString(netR, 2) + ";" +
           DoubleToString(pnl, 2) + ";" + DoubleToString(g_eq, 2));

   SendTelegram(StringFormat("MICRO SCALP %s #%d %s %s | %+.2fR | equity $%.0f",
                rs, o.id, o.dir > 0 ? "BUY" : "SELL", g_sym, netR, g_eq));
   RemoveOrd(i);
}

void ManageOrders()
{
   int n = ArraySize(g_ord);
   if(n == 0) return;
   double bid = SymbolInfoDouble(g_sym, SYMBOL_BID);
   double ask = SymbolInfoDouble(g_sym, SYMBOL_ASK);
   if(bid <= 0 || ask <= 0) return;
   datetime now = TimeCurrent();

   for(int i = n - 1; i >= 0; i--)
   {
      bool buy = (g_ord[i].dir > 0);

      if(g_ord[i].state == 0)                                // pending limit
      {
         bool fill = buy ? (ask <= g_ord[i].entry) : (bid >= g_ord[i].entry);
         if(fill)
         {
            g_ord[i].state  = 1;
            g_ord[i].filled = now;
            g_filled++;
         }
         else
         {
            bool missed  = buy ? (bid >= g_ord[i].tp) : (ask <= g_ord[i].tp);   // target reached without us
            bool invalid = buy ? (bid <= g_ord[i].sl) : (ask >= g_ord[i].sl);   // setup already failed
            if(now >= g_ord[i].expire)  { g_expNoFill++; RemoveOrd(i); }
            else if(missed || invalid)  { g_missed++;    RemoveOrd(i); }
            continue;
         }
      }

      // open position
      double risk = g_ord[i].riskDist;
      if(buy)
      {
         if(bid <= g_ord[i].sl)
         {
            double ex = MathMin(bid, g_ord[i].sl) - g_slip;
            CloseTrade(i, ex, (ex - g_ord[i].entry) / risk, 1);
         }
         else if(bid >= g_ord[i].tp)
            CloseTrade(i, g_ord[i].tp, (g_ord[i].tp - g_ord[i].entry) / risk, 0);
         else if((long)now - (long)g_ord[i].filled >= MAX_HOLD_MIN * 60)
            CloseTrade(i, bid, (bid - g_ord[i].entry) / risk, 2);
      }
      else
      {
         if(ask >= g_ord[i].sl)
         {
            double ex = MathMax(ask, g_ord[i].sl) + g_slip;
            CloseTrade(i, ex, (g_ord[i].entry - ex) / risk, 1);
         }
         else if(ask <= g_ord[i].tp)
            CloseTrade(i, g_ord[i].tp, (g_ord[i].entry - g_ord[i].tp) / risk, 0);
         else if((long)now - (long)g_ord[i].filled >= MAX_HOLD_MIN * 60)
            CloseTrade(i, ask, (g_ord[i].entry - ask) / risk, 2);
      }
   }
}

//==================================================================
// RESULTS
//==================================================================
void PrintStats()
{
   int closed = g_cTP + g_cSL + g_cTime;
   double pf = (g_grossLoss > 0) ? g_grossWin / g_grossLoss : 0;
   double wr = (closed > 0) ? 100.0 * g_wins / closed : 0;
   double avgCost = (closed > 0) ? g_sumCostR / closed : 0;
   double avgSpreadR = (g_placed > 0) ? g_sumSpreadR / g_placed : 0;
   double be = 100.0 * (1.0 + avgCost) / (1.0 + RR);

   Print("================ MICRO SCALP RESULTS: ", g_sym, " ================");
   Print(StringFormat("Setups placed %d | filled %d (%.0f%%) | expired unfilled %d | missed/invalidated %d | skipped: spread %d, risk %d",
         g_placed, g_filled, g_placed > 0 ? 100.0 * g_filled / g_placed : 0, g_expNoFill, g_missed, g_skipSpread, g_skipRisk));
   Print(StringFormat("Closed trades %d over %d days (%.1f/day) | TP %d | SL %d | time-exit %d",
         closed, g_days, g_days > 0 ? (double)closed / g_days : 0, g_cTP, g_cSL, g_cTime));
   Print(StringFormat("Win rate %.1f%% | break-even win rate at RR %.2f incl. measured costs: %.1f%%", wr, RR, be));
   Print(StringFormat("Profit factor %.2f | net %+.2fR | avg %+.3fR/trade | net $%+.0f | max drawdown $%.0f | final equity $%.0f",
         pf, g_sumR, closed > 0 ? g_sumR / closed : 0, g_eq - START_EQUITY, g_maxDD, g_eq));
   Print(StringFormat("Avg commission cost %.3fR | avg spread as fraction of stop %.3f | avg stop distance %s | trades below min lot %d",
         avgCost, avgSpreadR, DoubleToString(closed > 0 ? g_sumRisk / closed : 0, g_digits), g_belowMinLot));
   for(int s = 0; s < 3; s++)
      if(g_sN[s] > 0)
         Print(StringFormat("  %-8s n=%d  win %.1f%%  net %+.2fR", SessName(s), g_sN[s], 100.0 * g_sW[s] / g_sN[s], g_sR[s]));
   for(int d = 0; d < 2; d++)
      if(g_dirN[d] > 0)
         Print(StringFormat("  %-8s n=%d  win %.1f%%  net %+.2fR", d == 0 ? "BUY" : "SELL", g_dirN[d], 100.0 * g_dirW[d] / g_dirN[d], g_dirR[d]));
   Print(StringFormat("Daily-loss halts %d | consecutive-loss pauses %d", g_haltDays, g_pauses));
   Print("=================================================================");
}

//==================================================================
// EVENTS
//==================================================================
int OnInit()
{
   g_tester = (bool)MQLInfoInteger(MQL_TESTER);
   g_sym = _Symbol;
   if(!SymbolSelect(g_sym, true)) return INIT_FAILED;
   InitAsset();
   g_eq = START_EQUITY; g_dayStartEq = START_EQUITY; g_peak = START_EQUITY;
   ArrayInitialize(g_sN, 0); ArrayInitialize(g_sW, 0); ArrayInitialize(g_sR, 0.0);
   ArrayInitialize(g_dirN, 0); ArrayInitialize(g_dirW, 0); ArrayInitialize(g_dirR, 0.0);
   g_logName = (g_tester ? "tester_" : "") + "micro_scalp_" + g_sym + ".csv";
   Print("MICRO SCALP started on ", g_sym, " | sweep ", DoubleToString(g_sMin, g_digits), "-", DoubleToString(g_sMax, g_digits),
         " | SL pad ", DoubleToString(g_pad, g_digits), " | slip ", DoubleToString(g_slip, g_digits),
         " | value per 1.0 price move per lot ", DoubleToString(g_vpu, 2));
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   if(g_tester) PrintStats();
}

void OnTick()
{
   CheckDay();
   ManageOrders();
   datetime t0 = iTime(g_sym, PERIOD_M1, 0);
   if(t0 != 0 && t0 != g_lastBar0)
   {
      g_lastBar0 = t0;
      OnNewBar();
   }
}

double OnTester()
{
   return g_sumR;
}
//+------------------------------------------------------------------+
