import { useState, useEffect, useCallback, useRef } from "react";

const API = "/api";
const CATEGORIES = ["All","Forex","Stocks","Crypto"];
const CAT_ICONS = { Forex:"💱", Stocks:"📈", Crypto:"₿" };

const C = {
  bg:      "#060609",
  card:    "#0d0d16",
  border:  "#1a1a2e",
  gold:    "#f59e0b",
  green:   "#10b981",
  red:     "#ef4444",
  blue:    "#3b82f6",
  purple:  "#8b5cf6",
  text:    "#e2e8f0",
  muted:   "#64748b",
  dim:     "#334155",
};

// ── Utility ──────────────────────────────────────────────────
const fmt = (v, d=5) => v ? Number(v).toFixed(d) : "—";
const pad = n => String(n).padStart(2,"0");

// ── Clock ─────────────────────────────────────────────────────
function Clock() {
  const [now,setNow] = useState(new Date());
  useEffect(()=>{const t=setInterval(()=>setNow(new Date()),1000);return()=>clearInterval(t);},[]);
  const p = pad;
  return (
    <div style={{fontFamily:"JetBrains Mono",fontSize:13,color:C.gold,letterSpacing:1}}>
      {p(now.getUTCHours())}:{p(now.getUTCMinutes())}:{p(now.getUTCSeconds())} UTC
    </div>
  );
}

// ── Session indicator ─────────────────────────────────────────
function Sessions() {
  const [now,setNow] = useState(new Date());
  useEffect(()=>{const t=setInterval(()=>setNow(new Date()),60000);return()=>clearInterval(t);},[]);
  const h = now.getUTCHours()+now.getUTCMinutes()/60;
  const sessions = [
    {name:"Tokyo",   open:0,  close:9,  color:"#60a5fa"},
    {name:"London",  open:7,  close:16, color:"#34d399"},
    {name:"New York",open:12, close:21, color:"#f59e0b"},
  ];
  return (
    <div style={{display:"flex",gap:6}}>
      {sessions.map(s=>{
        const on=h>=s.open&&h<s.close;
        return <div key={s.name} style={{
          padding:"3px 8px",borderRadius:20,fontSize:10,fontWeight:600,
          background:on?s.color+"22":"transparent",
          border:`1px solid ${on?s.color:"#1a1a2e"}`,
          color:on?s.color:C.dim,
        }}>{on?"●":"○"} {s.name}</div>;
      })}
    </div>
  );
}

// ── Signal Card ───────────────────────────────────────────────
function SignalCard({ sig, onSelect, isSelected }) {
  const dir   = sig.direction;
  const dc    = dir==="BUY"?C.green:dir==="SELL"?C.red:C.muted;
  const conf  = sig.confidence||0;
  const cc    = conf>=70?C.green:conf>=50?C.gold:C.red;
  const isAct = dir!=="HOLD";

  return (
    <div onClick={()=>onSelect(sig)}
      style={{
        background: isSelected?"#0f1729":C.card,
        border:`1px solid ${isSelected?"#3b82f6":isAct?dc+"44":C.border}`,
        borderRadius:12,padding:16,cursor:"pointer",
        transition:"all 0.2s",
        animation:"fadeIn 0.3s ease",
        boxShadow:isSelected?"0 0 0 1px #3b82f644":isAct?`0 0 20px ${dc}11`:"none",
      }}>

      {/* Header */}
      <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",marginBottom:12}}>
        <div>
          <div style={{display:"flex",alignItems:"center",gap:6,marginBottom:4}}>
            <span style={{color:C.muted,fontSize:10}}>{CAT_ICONS[sig.category]}</span>
            <span style={{color:C.text,fontSize:14,fontWeight:700}}>{sig.label||sig.pair}</span>
          </div>
          {isAct&&<div style={{display:"flex",gap:6,alignItems:"center"}}>
            <span style={{color:dc,fontSize:22,fontWeight:900,lineHeight:1}}>{dir}</span>
            <span style={{color:dc,fontSize:10,fontWeight:700,background:dc+"22",
              border:`1px solid ${dc}44`,padding:"2px 7px",borderRadius:20}}>
              {sig.strength}
            </span>
          </div>}
          {!isAct&&<div style={{color:C.muted,fontSize:12}}>WAIT</div>}
        </div>
        <div style={{textAlign:"right"}}>
          <div style={{color:cc,fontSize:24,fontWeight:800,fontFamily:"JetBrains Mono"}}>{conf}%</div>
          <div style={{color:C.dim,fontSize:9,letterSpacing:1}}>CONFIDENCE</div>
        </div>
      </div>

      {/* Levels */}
      {isAct&&(
        <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:6,marginBottom:10}}>
          {[
            ["ENTRY",  sig.entry,         C.gold],
            ["SL",     sig.stop_loss,     C.red],
            ["TP1",    sig.take_profit_1, C.green],
            ["TP2",    sig.take_profit_2, "#34d399"],
          ].map(([l,v,c])=>(
            <div key={l} style={{background:"#060609",borderRadius:7,padding:"7px 9px"}}>
              <div style={{color:C.dim,fontSize:9,marginBottom:2}}>{l}</div>
              <div style={{color:c,fontSize:12,fontWeight:700,fontFamily:"JetBrains Mono"}}>{fmt(v)}</div>
            </div>
          ))}
        </div>
      )}

      {/* Indicators mini row */}
      {sig.indicators&&sig.indicators.rsi&&(
        <div style={{display:"flex",gap:8,alignItems:"center"}}>
          <span style={{color:C.dim,fontSize:10}}>RSI</span>
          <span style={{color:sig.indicators.rsi<30?C.green:sig.indicators.rsi>70?C.red:C.text,
            fontSize:11,fontWeight:700,fontFamily:"JetBrains Mono"}}>
            {sig.indicators.rsi}
          </span>
          <span style={{color:C.dim,fontSize:10,marginLeft:4}}>EMA</span>
          <span style={{color:sig.indicators.ema9>sig.indicators.ema21?C.green:C.red,
            fontSize:11,fontWeight:700}}>
            {sig.indicators.ema9>sig.indicators.ema21?"↑":"↓"}
          </span>
          <span style={{color:C.dim,fontSize:10,marginLeft:4}}>MACD</span>
          <span style={{color:sig.indicators.macd>sig.indicators.macd_signal?C.green:C.red,
            fontSize:11,fontWeight:700}}>
            {sig.indicators.macd>sig.indicators.macd_signal?"↑":"↓"}
          </span>
          <div style={{marginLeft:"auto",color:C.dim,fontSize:9}}>
            {sig.timestamp?new Date(sig.timestamp).toLocaleTimeString():""}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Signal Detail Panel ───────────────────────────────────────
function DetailPanel({ sig, onOutcome }) {
  if(!sig) return (
    <div style={{background:C.card,border:`1px solid ${C.border}`,borderRadius:12,
      padding:32,textAlign:"center",height:"100%",display:"flex",
      flexDirection:"column",alignItems:"center",justifyContent:"center",gap:12}}>
      <div style={{fontSize:32}}>📊</div>
      <div style={{color:C.muted,fontSize:14}}>Select a signal to see details</div>
    </div>
  );

  const dir  = sig.direction;
  const dc   = dir==="BUY"?C.green:dir==="SELL"?C.red:C.muted;
  const isAct= dir!=="HOLD";
  const conf = sig.confidence||0;
  const cc   = conf>=70?C.green:conf>=50?C.gold:C.red;
  const ind  = sig.indicators||{};
  const bull = ind.bull_score||0;
  const bear = ind.bear_score||0;
  const total= bull+bear||1;

  return (
    <div style={{background:C.card,border:`1px solid ${C.border}`,borderRadius:12,
      padding:20,overflowY:"auto",height:"100%"}}>

      {/* Title */}
      <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",marginBottom:16}}>
        <div>
          <div style={{color:C.muted,fontSize:10,letterSpacing:2,marginBottom:4}}>
            {CAT_ICONS[sig.category]} {sig.category?.toUpperCase()}
          </div>
          <div style={{color:C.text,fontSize:20,fontWeight:800}}>{sig.label||sig.pair}</div>
        </div>
        <div style={{textAlign:"right"}}>
          <div style={{color:dc,fontSize:36,fontWeight:900,lineHeight:1}}>{dir}</div>
          {isAct&&<div style={{color:dc,fontSize:10,fontWeight:700}}>{sig.strength}</div>}
        </div>
      </div>

      {/* Confidence bar */}
      <div style={{marginBottom:14}}>
        <div style={{display:"flex",justifyContent:"space-between",marginBottom:4}}>
          <span style={{color:C.muted,fontSize:10}}>CONFIDENCE</span>
          <span style={{color:cc,fontSize:12,fontWeight:700}}>{conf}%</span>
        </div>
        <div style={{background:"#0d0d16",borderRadius:4,height:6,overflow:"hidden"}}>
          <div style={{background:cc,height:"100%",width:`${conf}%`,transition:"width 0.5s ease"}} />
        </div>
      </div>

      {/* Action box */}
      {isAct&&(
        <div style={{background:dc+"11",border:`1px solid ${dc}33`,borderRadius:8,
          padding:"10px 14px",marginBottom:14}}>
          <div style={{color:C.dim,fontSize:9,letterSpacing:2,marginBottom:5}}>SIGNAL ACTION</div>
          <div style={{color:dc,fontSize:12,lineHeight:1.6,fontWeight:600}}>{sig.action}</div>
        </div>
      )}

      {/* Levels */}
      {isAct&&(
        <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:8,marginBottom:14}}>
          {[
            ["📍 ENTRY",   sig.entry,         C.gold,  "Enter here"],
            ["🛑 STOP LOSS",sig.stop_loss,    C.red,   `${sig.sl_pips} pips risk`],
            ["✅ TP1",     sig.take_profit_1, C.green, `${sig.tp1_pips} pips profit`],
            ["🎯 TP2",     sig.take_profit_2, "#34d399","Extended target"],
          ].map(([l,v,c,h])=>(
            <div key={l} style={{background:"#060609",borderRadius:8,padding:"10px 12px"}}>
              <div style={{color:C.dim,fontSize:9,marginBottom:3}}>{l}</div>
              <div style={{color:c,fontSize:15,fontWeight:700,fontFamily:"JetBrains Mono"}}>{fmt(v)}</div>
              <div style={{color:C.muted,fontSize:10,marginTop:2}}>{h}</div>
            </div>
          ))}
        </div>
      )}

      {/* Bull/Bear bar */}
      {isAct&&(
        <div style={{marginBottom:14}}>
          <div style={{display:"flex",justifyContent:"space-between",marginBottom:4}}>
            <span style={{color:C.green,fontSize:10,fontWeight:700}}>BULL {bull}</span>
            <span style={{color:C.red,fontSize:10,fontWeight:700}}>BEAR {bear}</span>
          </div>
          <div style={{background:"#1a1a2e",borderRadius:4,height:6,overflow:"hidden",display:"flex"}}>
            <div style={{background:`linear-gradient(90deg,${C.green},#34d399)`,
              height:"100%",width:`${bull/total*100}%`,transition:"width 0.5s"}} />
            <div style={{background:`linear-gradient(90deg,#ef4444,#f87171)`,
              height:"100%",flex:1}} />
          </div>
        </div>
      )}

      {/* Indicators */}
      {Object.keys(ind).length>0&&(
        <div style={{marginBottom:14}}>
          <div style={{color:C.dim,fontSize:9,letterSpacing:2,marginBottom:8}}>INDICATORS</div>
          <div style={{display:"grid",gridTemplateColumns:"repeat(3,1fr)",gap:6}}>
            {[
              ["RSI",    ind.rsi,        ind.rsi<30?C.green:ind.rsi>70?C.red:C.text],
              ["EMA9",   ind.ema9,       C.gold],
              ["EMA21",  ind.ema21,      C.muted],
              ["VWAP",   ind.vwap,       C.blue],
              ["Support",ind.support,    C.green],
              ["Resist", ind.resistance, C.red],
            ].map(([l,v,c])=>(
              <div key={l} style={{background:"#060609",borderRadius:6,padding:"7px 9px",textAlign:"center"}}>
                <div style={{color:C.dim,fontSize:9,marginBottom:2}}>{l}</div>
                <div style={{color:c,fontSize:11,fontWeight:700,fontFamily:"JetBrains Mono"}}>
                  {v?Number(v).toFixed(4):"—"}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Reasons */}
      {sig.reasons?.length>0&&(
        <div style={{marginBottom:14}}>
          <div style={{color:C.dim,fontSize:9,letterSpacing:2,marginBottom:8}}>WHY THIS SIGNAL</div>
          {sig.reasons.map((r,i)=>(
            <div key={i} style={{display:"flex",gap:8,marginBottom:6,alignItems:"flex-start"}}>
              <span style={{color:C.gold,flexShrink:0,fontSize:12}}>▸</span>
              <span style={{color:"#94a3b8",fontSize:12,lineHeight:1.5}}>{r}</span>
            </div>
          ))}
        </div>
      )}

      {/* Step by step */}
      {isAct&&(
        <div style={{background:"#060609",borderRadius:8,padding:14,marginBottom:14}}>
          <div style={{color:C.dim,fontSize:9,letterSpacing:2,marginBottom:10}}>STEP BY STEP</div>
          {[
            {n:"1",t:`Open ${dir} at ${fmt(sig.entry)}`,c:C.gold},
            {n:"2",t:`Set Stop Loss at ${fmt(sig.stop_loss)} — mandatory`,c:C.red},
            {n:"3",t:`At TP1 (${fmt(sig.take_profit_1)}), close 50% of position`,c:C.green},
            {n:"4",t:`Move stop to entry — let rest run to TP2 (${fmt(sig.take_profit_2)})`,c:"#34d399"},
            {n:"5",t:"If SL hit — close and wait for next signal. No revenge trading.",c:C.muted},
          ].map(({n,t,c})=>(
            <div key={n} style={{display:"flex",gap:10,marginBottom:8,alignItems:"flex-start"}}>
              <div style={{width:20,height:20,borderRadius:"50%",background:"#1a1a2e",
                color:C.gold,fontSize:10,fontWeight:700,display:"flex",
                alignItems:"center",justifyContent:"center",flexShrink:0}}>{n}</div>
              <div style={{color:c,fontSize:12,lineHeight:1.5}}>{t}</div>
            </div>
          ))}
        </div>
      )}

      {/* Warnings */}
      {sig.warnings?.length>0&&sig.warnings[0]&&(
        <div style={{marginBottom:14}}>
          {sig.warnings.map((w,i)=>(
            <div key={i} style={{background:"#1a1200",border:"1px solid #f59e0b33",
              borderRadius:6,padding:"7px 10px",marginBottom:5,
              color:C.gold,fontSize:11}}>{w}</div>
          ))}
        </div>
      )}

      {/* Outcome buttons */}
      {isAct&&onOutcome&&(
        <div>
          <div style={{color:C.dim,fontSize:9,letterSpacing:2,marginBottom:8}}>MARK RESULT</div>
          <div style={{display:"flex",gap:8}}>
            {["WIN","LOSS","BREAKEVEN"].map(o=>(
              <button key={o} onClick={()=>onOutcome(o)} style={{
                flex:1,padding:"8px 4px",borderRadius:8,cursor:"pointer",
                fontSize:11,fontWeight:700,
                background:o==="WIN"?"#052e16":o==="LOSS"?"#1a0a0a":"#0d0d16",
                border:`1px solid ${o==="WIN"?"#10b98144":o==="LOSS"?"#ef444444":"#1a1a2e"}`,
                color:o==="WIN"?C.green:o==="LOSS"?C.red:C.muted,
              }}>{o==="WIN"?"✅ WIN":o==="LOSS"?"❌ LOSS":"➡ B/E"}</button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Market Overview Bar ───────────────────────────────────────
function MarketBar({ signals }) {
  if(!signals.length) return null;
  const active = signals.filter(s=>s.direction!=="HOLD");
  const buys   = active.filter(s=>s.direction==="BUY").length;
  const sells  = active.filter(s=>s.direction==="SELL").length;

  return (
    <div style={{background:C.card,border:`1px solid ${C.border}`,
      borderRadius:10,padding:"10px 16px",
      display:"flex",alignItems:"center",gap:16,flexWrap:"wrap"}}>
      <div style={{display:"flex",gap:12}}>
        <span style={{color:C.green,fontWeight:700,fontSize:13}}>▲ {buys} BUY</span>
        <span style={{color:C.red,fontWeight:700,fontSize:13}}>▼ {sells} SELL</span>
        <span style={{color:C.muted,fontSize:13}}>{signals.length-active.length} WAIT</span>
      </div>
      <div style={{flex:1,background:"#0d0d16",borderRadius:4,height:5,overflow:"hidden",display:"flex"}}>
        <div style={{background:C.green,width:`${buys/signals.length*100}%`,height:"100%"}} />
        <div style={{background:C.red,width:`${sells/signals.length*100}%`,height:"100%"}} />
      </div>
      <div style={{color:C.muted,fontSize:10}}>
        {active.length} active signal{active.length!==1?"s":""}
      </div>
    </div>
  );
}

// ── Main App ─────────────────────────────────────────────────
export default function App() {
  const [signals,  setSignals]   = useState([]);
  const [selected, setSelected]  = useState(null);
  const [scanning, setScanning]  = useState(false);
  const [online,   setOnline]    = useState(false);
  const [lastScan, setLastScan]  = useState(null);
  const [filter,   setFilter]    = useState("All");
  const [scanCount,setScanCount] = useState(0);

  const fetchSignals = useCallback(async()=>{
    try{
      const r = await fetch(`${API}/signals`);
      const d = await r.json();
      const sigs = d.signals||[];
      setSignals(sigs);
      setLastScan(d.last_scan);
      setScanning(d.scanning||false);
      if(sigs.length>0) setOnline(true);
    }catch{ setOnline(false); }
  },[]);

  const checkHealth = useCallback(async()=>{
    try{
      const r = await fetch(`${API}/health`);
      const d = await r.json();
      setOnline(d.status==="online");
      setScanning(d.scanning||false);
      setScanCount(d.scan_count||0);
    }catch{ setOnline(false); }
  },[]);

  const triggerScan = async()=>{
    setScanning(true);
    try{ await fetch(`${API}/scan`,{method:"POST"}); }catch{}
    setTimeout(fetchSignals, 3000);
  };

  const handleOutcome = async(outcome)=>{
    try{ await fetch(`${API}/outcome`,{method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({outcome})}); }catch{}
  };

  useEffect(()=>{
    checkHealth(); fetchSignals();
    const t1=setInterval(fetchSignals,30000);
    const t2=setInterval(checkHealth,10000);
    return()=>{ clearInterval(t1); clearInterval(t2); };
  },[fetchSignals,checkHealth]);

  const filtered = filter==="All"
    ? signals
    : signals.filter(s=>s.category===filter);

  const activeSignals = signals.filter(s=>s.direction!=="HOLD");

  return (
    <div style={{minHeight:"100vh",background:C.bg,display:"flex",flexDirection:"column"}}>

      {/* ── Header ── */}
      <header style={{background:C.card,borderBottom:`1px solid ${C.border}`,
        padding:"14px 24px",display:"flex",justifyContent:"space-between",
        alignItems:"center",flexShrink:0}}>
        <div style={{display:"flex",alignItems:"center",gap:16}}>
          <div style={{display:"flex",alignItems:"baseline",gap:6}}>
            <span style={{fontSize:24,fontWeight:900,color:C.text,letterSpacing:-1}}>ATLAS</span>
            <span style={{fontSize:10,color:C.gold,letterSpacing:3,
              background:C.gold+"22",border:`1px solid ${C.gold}44`,
              padding:"2px 7px",borderRadius:20}}>TRADING</span>
          </div>
          <Sessions />
        </div>

        <div style={{display:"flex",alignItems:"center",gap:14}}>
          <Clock />

          {/* Scan button */}
          <button onClick={triggerScan} disabled={scanning||!online}
            style={{display:"flex",alignItems:"center",gap:6,
              background:scanning?"#1a1a2e":C.gold,
              color:scanning?"#555":"#000",border:"none",
              padding:"8px 16px",borderRadius:8,fontWeight:800,
              fontSize:12,cursor:scanning?"not-allowed":"pointer",letterSpacing:1,
              transition:"all 0.2s"}}>
            {scanning?(
              <><span style={{animation:"spin 1s linear infinite",display:"inline-block"}}>⟳</span> SCANNING...</>
            ):(
              <>⚡ SCAN ALL</>
            )}
          </button>

          {/* Online status */}
          <div style={{display:"flex",alignItems:"center",gap:5}}>
            <div style={{width:7,height:7,borderRadius:"50%",
              background:online?C.green:C.red,
              boxShadow:online?`0 0 6px ${C.green}`:undefined,
              animation:online?"pulse 2s infinite":undefined}} />
            <span style={{color:online?C.green:C.red,fontSize:11,fontWeight:600}}>
              {online?"LIVE":"OFFLINE"}
            </span>
          </div>
        </div>
      </header>

      {/* ── Offline banner ── */}
      {!online&&(
        <div style={{background:"#1a0a00",borderBottom:`1px solid ${C.red}33`,
          color:C.red,padding:"10px 24px",fontSize:12}}>
          ⚠️ Cannot reach ATLAS server. Make sure the backend is running and deployed.
        </div>
      )}

      {/* ── Scan status bar ── */}
      {scanning&&(
        <div style={{background:"#0a1628",borderBottom:`1px solid ${C.blue}33`,
          padding:"8px 24px",display:"flex",alignItems:"center",gap:10}}>
          <div style={{width:"100%",background:"#1a2a3a",borderRadius:2,height:3,overflow:"hidden"}}>
            <div style={{height:"100%",background:C.blue,
              animation:"scanLine 3s ease infinite"}} />
          </div>
          <span style={{color:C.blue,fontSize:11,flexShrink:0}}>Scanning markets...</span>
        </div>
      )}

      <main style={{flex:1,padding:"16px 24px",display:"flex",flexDirection:"column",gap:14,overflow:"hidden"}}>

        {/* Market overview */}
        {signals.length>0&&<MarketBar signals={signals} />}

        {/* Stats row */}
        <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:10}}>
          {[
            ["ACTIVE SIGNALS", activeSignals.length,     C.gold],
            ["BUY SIGNALS",    signals.filter(s=>s.direction==="BUY").length,  C.green],
            ["SELL SIGNALS",   signals.filter(s=>s.direction==="SELL").length, C.red],
            ["SCAN #",         scanCount,                C.blue],
          ].map(([l,v,c])=>(
            <div key={l} style={{background:C.card,border:`1px solid ${C.border}`,
              borderRadius:10,padding:"12px 16px",textAlign:"center"}}>
              <div style={{color:C.muted,fontSize:9,letterSpacing:2,marginBottom:4}}>{l}</div>
              <div style={{color:c,fontSize:24,fontWeight:800}}>{v}</div>
            </div>
          ))}
        </div>

        {/* Category filter */}
        <div style={{display:"flex",gap:6}}>
          {CATEGORIES.map(cat=>(
            <button key={cat} onClick={()=>setFilter(cat)} style={{
              padding:"6px 14px",borderRadius:20,cursor:"pointer",
              fontSize:11,fontWeight:600,
              background:filter===cat?"#1e2d45":"transparent",
              border:`1px solid ${filter===cat?C.blue+"66":C.border}`,
              color:filter===cat?C.blue:C.muted,
              transition:"all 0.15s",
            }}>{cat}</button>
          ))}
          {lastScan&&<div style={{marginLeft:"auto",color:C.dim,fontSize:10,
            display:"flex",alignItems:"center"}}>
            Last scan: {new Date(lastScan).toLocaleTimeString()}
          </div>}
        </div>

        {/* Content grid */}
        <div style={{flex:1,display:"grid",gridTemplateColumns:"1fr 380px",gap:14,
          overflow:"hidden",minHeight:0}}>

          {/* Signal cards */}
          <div style={{overflowY:"auto",display:"flex",flexDirection:"column",gap:10,paddingRight:4}}>
            {filtered.length===0?(
              <div style={{background:C.card,border:`1px solid ${C.border}`,borderRadius:12,
                padding:40,textAlign:"center"}}>
                <div style={{fontSize:32,marginBottom:10}}>📡</div>
                <div style={{color:C.muted,fontSize:14}}>
                  {online?"Click ⚡ SCAN ALL to get signals":"Connecting to ATLAS..."}
                </div>
              </div>
            ):(
              // Active signals first, then HOLD
              [...filtered.filter(s=>s.direction!=="HOLD"),
               ...filtered.filter(s=>s.direction==="HOLD")]
              .map(sig=>(
                <SignalCard key={sig.pair} sig={sig}
                  onSelect={setSelected}
                  isSelected={selected?.pair===sig.pair} />
              ))
            )}
          </div>

          {/* Detail panel */}
          <div style={{overflowY:"auto"}}>
            <DetailPanel sig={selected} onOutcome={handleOutcome} />
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer style={{borderTop:`1px solid ${C.border}`,
        padding:"10px 24px",display:"flex",justifyContent:"space-between",
        alignItems:"center",background:C.card,flexShrink:0}}>
        <div style={{color:C.dim,fontSize:10}}>
          ATLAS Trading System — Auto-scans every 5 minutes
        </div>
        <div style={{color:C.dim,fontSize:10}}>
          Signals sent to Telegram when confidence ≥ 65%
        </div>
      </footer>
    </div>
  );
}
