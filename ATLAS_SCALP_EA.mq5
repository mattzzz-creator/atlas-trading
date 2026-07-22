//+------------------------------------------------------------------+
//| ATLAS Scalp EA — EMA/RSI Momentum Scalp                          |
//| Pair: EURUSD only                                                 |
//| Strategy: Fast EMA9/EMA21 cross + RSI confirmation, tight stops   |
//+------------------------------------------------------------------+
#property copyright "ATLAS Trading System"
#property version   "1.00"
#include <Trade\Trade.mqh>

CTrade trade;

input string ATLAS_URL      = "https://atlas-trading-9kir.onrender.com";
input double RISK_PERCENT   = 1.0;    // % of balance per trade
input int    MIN_CONFIDENCE = 65;     // Min confidence to trade
input int    SCAN_SECONDS   = 30;     // Check every 30 seconds — scalping needs faster polling
input int    MAGIC          = 20260719;
input int    MAX_TRADES_PER_DAY = 8;   // Scalping fires more often than the gold swing strategy
input double MAX_RISK_DOLLARS   = 5.0; // Hard $ cap — skip trade if min lot risks more than this
input double MAX_SPREAD_PIPS    = 2.0; // Requirement: skip trade if spread is too wide — critical for scalping

// Daily trade counter
int      g_tradesToday = 0;
datetime g_counterDay  = 0;

void ResetDailyCounterIfNewDay() {
    MqlDateTime dt;
    TimeToStruct(TimeGMT(), dt);
    datetime today = StringToTime(StringFormat("%04d.%02d.%02d 00:00:00", dt.year, dt.mon, dt.day));
    if(today != g_counterDay) {
        g_counterDay  = today;
        g_tradesToday = 0;
        Print("[ATLAS SCALP] New day — trade counter reset");
    }
}

// EUR/USD symbol name on this broker
string FX_SYMBOL = "";

string FindFXSymbol() {
    string candidates[] = {"EURUSD","EURUSDm","EURUSD.a","EURUSDpro"};
    for(int i=0; i<ArraySize(candidates); i++)
        if(SymbolSelect(candidates[i], true))
            return candidates[i];
    return "";
}

bool HasOpenTrade() {
    for(int i=PositionsTotal()-1; i>=0; i--)
        if(PositionGetSymbol(i)==FX_SYMBOL &&
           PositionGetInteger(POSITION_MAGIC)==MAGIC)
            return true;
    return false;
}

double CalcLots(double entry, double sl) {
    double balance  = AccountInfoDouble(ACCOUNT_BALANCE);
    double riskAmt  = balance * RISK_PERCENT / 100.0;
    double point    = SymbolInfoDouble(FX_SYMBOL, SYMBOL_POINT);
    double tickVal  = SymbolInfoDouble(FX_SYMBOL, SYMBOL_TRADE_TICK_VALUE);
    double tickSize = SymbolInfoDouble(FX_SYMBOL, SYMBOL_TRADE_TICK_SIZE);
    double slDist   = MathAbs(entry - sl);
    if(slDist==0||tickVal==0||point==0) return 0.01;
    double slPts = slDist / point;
    double lots  = riskAmt / (slPts * tickVal / tickSize);
    double minL  = SymbolInfoDouble(FX_SYMBOL, SYMBOL_VOLUME_MIN);
    double step  = SymbolInfoDouble(FX_SYMBOL, SYMBOL_VOLUME_STEP);
    double maxL  = SymbolInfoDouble(FX_SYMBOL, SYMBOL_VOLUME_MAX);
    lots = MathFloor(lots/step)*step;
    return MathMax(minL, MathMin(maxL, lots));
}

string GetVal(string json, string key) {
    string s1 = "\""+key+"\":\"";
    string s2 = "\""+key+"\":";
    int pos = StringFind(json,s1);
    bool str = true;
    if(pos<0){pos=StringFind(json,s2);str=false;}
    if(pos<0) return "";
    pos += str ? StringLen(s1) : StringLen(s2);
    while(pos<StringLen(json)&&StringGetCharacter(json,pos)==' ') pos++;
    int end=pos;
    while(end<StringLen(json)){
        ushort ch=StringGetCharacter(json,end);
        if(str&&ch=='"') break;
        if(!str&&(ch==','||ch=='}'||ch==']')) break;
        end++;
    }
    return StringSubstr(json,pos,end-pos);
}

// ── Requirement: spread check — scalping dies fastest to wide spreads ──
bool SpreadOK() {
    long spreadPts = SymbolInfoInteger(FX_SYMBOL, SYMBOL_SPREAD);
    double point   = SymbolInfoDouble(FX_SYMBOL, SYMBOL_POINT);
    double digits  = SymbolInfoInteger(FX_SYMBOL, SYMBOL_DIGITS);
    // Convert points to pips (5-digit broker: 1 pip = 10 points)
    double spreadPips = (digits == 5 || digits == 3) ? spreadPts / 10.0 : spreadPts;
    if(spreadPips > MAX_SPREAD_PIPS) {
        Print("[ATLAS SCALP] ⛔ Spread too wide: ", spreadPips, " pips > ", MAX_SPREAD_PIPS, " cap — skipping");
        return false;
    }
    return true;
}

void CheckScalpSignal() {
    if(FX_SYMBOL == "") return;

    ResetDailyCounterIfNewDay();
    if(g_tradesToday >= MAX_TRADES_PER_DAY) {
        Print("[ATLAS SCALP] Daily trade limit reached (", g_tradesToday, "/", MAX_TRADES_PER_DAY, ") — waiting for tomorrow");
        return;
    }

    if(HasOpenTrade()) {
        Print("[ATLAS SCALP] Already have open trade — waiting");
        return;
    }

    // Only trade London through NY session (07:00-16:00 UTC) — matches server-side filter
    MqlDateTime dt;
    TimeToStruct(TimeGMT(), dt);
    int h = dt.hour;
    if(h < 7 || h >= 16) {
        Print("[ATLAS SCALP] Off session — waiting for London/NY hours");
        return;
    }

    // ── Requirement: spread filter, checked BEFORE calling the server ──
    if(!SpreadOK()) return;

    string url = ATLAS_URL + "/api/signal/EURUSD";
    string headers = "User-Agent: ATLAS-SCALP-EA/1.0\r\n";
    char post[], result[];
    string resHeaders;

    int code = WebRequest("GET", url, headers, 10000, post, result, resHeaders);
    if(code != 200) {
        if(code > 0) Print("[ATLAS SCALP] HTTP ", code);
        return;
    }

    string json = CharArrayToString(result);
    string direction  = GetVal(json, "direction");
    string strength   = GetVal(json, "strength");

    if(direction == "HOLD" || direction == "") {
        string reason = GetVal(json, "action");
        Print("[ATLAS SCALP] ⏸ ", StringSubstr(reason, 0, 80));
        return;
    }

    int confidence = (int)StringToDouble(GetVal(json, "confidence"));
    if(confidence < MIN_CONFIDENCE) {
        Print("[ATLAS SCALP] Confidence ", confidence, "% below minimum ", MIN_CONFIDENCE, "%");
        return;
    }
    if(strength == "WEAK") {
        Print("[ATLAS SCALP] Signal is WEAK — skipping");
        return;
    }

    double entry = StringToDouble(GetVal(json, "entry"));
    double sl    = StringToDouble(GetVal(json, "stop_loss"));
    double tp1   = StringToDouble(GetVal(json, "take_profit_1"));
    double tp2   = StringToDouble(GetVal(json, "take_profit_2"));

    if(entry==0||sl==0||tp1==0) {
        Print("[ATLAS SCALP] Invalid levels");
        return;
    }

    // Verify RR >= 1:1.4 (target is 1:1.5)
    double risk   = MathAbs(entry-sl);
    double reward = MathAbs(tp1-entry);
    if(reward < risk*1.4) {
        Print("[ATLAS SCALP] RR too low — skip");
        return;
    }

    double lots = CalcLots(entry, sl);

    // ── Hard safety check: refuse to take a trade sized bigger than we can afford ──
    double point    = SymbolInfoDouble(FX_SYMBOL, SYMBOL_POINT);
    double tickVal  = SymbolInfoDouble(FX_SYMBOL, SYMBOL_TRADE_TICK_VALUE);
    double tickSize = SymbolInfoDouble(FX_SYMBOL, SYMBOL_TRADE_TICK_SIZE);
    double slDist   = MathAbs(entry - sl);
    double actualRiskDollars = (slDist / point) * (tickVal / tickSize) * lots;
    if(actualRiskDollars > MAX_RISK_DOLLARS) {
        Print("[ATLAS SCALP] ⛔ Skipped — min lot (", lots, ") would risk $",
              DoubleToString(actualRiskDollars,2), " > cap $", DoubleToString(MAX_RISK_DOLLARS,2));
        return;
    }

    trade.SetExpertMagicNumber(MAGIC);
    trade.SetDeviationInPoints(20); // Tighter slippage tolerance than gold — scalping needs precise fills

    bool ok = false;
    string comment = "ATLAS SCALP " + direction + " " + IntegerToString(confidence) + "%";

    if(direction == "BUY")
        ok = trade.Buy(lots, FX_SYMBOL, 0, sl, tp1, comment);
    else if(direction == "SELL")
        ok = trade.Sell(lots, FX_SYMBOL, 0, sl, tp1, comment);

    if(ok) {
        g_tradesToday++;
        Print("════════════════════════════════");
        Print("[ATLAS SCALP] ✅ TRADE OPENED! (", g_tradesToday, "/", MAX_TRADES_PER_DAY, " today)");
        Print("[ATLAS SCALP] ", direction, " EURUSD | ", lots, " lots");
        Print("[ATLAS SCALP] Entry: ", entry, " | SL: ", sl, " | TP: ", tp1);
        Print("[ATLAS SCALP] Confidence: ", confidence, "% | ", strength);
        Print("════════════════════════════════");
    } else {
        int err = GetLastError();
        Print("[ATLAS SCALP] ❌ Failed — Error: ", err);
        if(err == 10018) Print("[ATLAS SCALP] Market closed");
        if(err == 10006) Print("[ATLAS SCALP] Request rejected — check lot size");
        if(err == 4756)  Print("[ATLAS SCALP] Trading disabled — enable Algo Trading");
    }
}

int OnInit() {
    FX_SYMBOL = FindFXSymbol();

    Print("════════════════════════════════");
    Print("[ATLAS SCALP EA] EMA/RSI Momentum Scalp Strategy");
    Print("[ATLAS SCALP EA] Server: ", ATLAS_URL);
    if(FX_SYMBOL != "")
        Print("[ATLAS SCALP EA] ✅ FX symbol: ", FX_SYMBOL);
    else
        Print("[ATLAS SCALP EA] ❌ EURUSD symbol NOT FOUND — check Market Watch");
    Print("[ATLAS SCALP EA] Min confidence: ", MIN_CONFIDENCE, "%");
    Print("[ATLAS SCALP EA] Risk per trade: ", RISK_PERCENT, "%");
    Print("[ATLAS SCALP EA] Max trades/day: ", MAX_TRADES_PER_DAY);
    Print("[ATLAS SCALP EA] Max spread: ", MAX_SPREAD_PIPS, " pips");
    Print("[ATLAS SCALP EA] Session: 07:00-16:00 UTC (London/NY)");
    Print("════════════════════════════════");

    ResetDailyCounterIfNewDay();
    EventSetTimer(SCAN_SECONDS);
    Comment("ATLAS SCALP EA\n" +
            (FX_SYMBOL!="" ? "✅ "+FX_SYMBOL : "❌ Symbol not found") +
            "\nMin: " + IntegerToString(MIN_CONFIDENCE) + "%" +
            "\nRisk: " + DoubleToString(RISK_PERCENT,1) + "%" +
            "\nMax trades: " + IntegerToString(MAX_TRADES_PER_DAY) + "/day" +
            "\nMax spread: " + DoubleToString(MAX_SPREAD_PIPS,1) + " pips" +
            "\nSession: 07:00-16:00 UTC");
    return INIT_SUCCEEDED;
}

void OnTimer() {
    MqlDateTime dt;
    TimeToStruct(TimeCurrent(), dt);
    if(dt.day_of_week==0||dt.day_of_week==6) return;
    CheckScalpSignal();
}

void OnDeinit(const int reason) {
    EventKillTimer();
    Print("[ATLAS SCALP EA] Stopped");
}

void OnTick() {}
