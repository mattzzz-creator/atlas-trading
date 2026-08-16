import React, { useState } from 'react';
import GoldLiveChart from './GoldLiveChart.jsx';
import AllSignalsSidebar from './AllSignalsSidebar.jsx';
import GuideHistoryTable from './GuideHistoryTable.jsx';

// Single chart with timeframe TABS on the chart itself (not the sidebar),
// a live signal FEED in the sidebar (fired signals across all 4 timeframes,
// not a static picker), and a combined setups/history table below.

const TIMEFRAMES = [
  { label: 'M1',  interval: '1m',  period: '7d',  pair: 'XAUUSD-GUIDE-M1'  },
  { label: 'M5',  interval: '5m',  period: '2d',  pair: 'XAUUSD-GUIDE-M5'  },
  { label: 'M15', interval: '15m', period: '5d',  pair: 'XAUUSD-GUIDE-M15' },
  { label: 'M30', interval: '30m', period: '10d', pair: 'XAUUSD-GUIDE-M30' },
];

export default function GoldTradingDashboard({ C, signals }) {
  const [activeTf, setActiveTf] = useState(TIMEFRAMES[1]); // default M5
  const [chartData, setChartData] = useState(null);
  const [detailOpen, setDetailOpen] = useState(false);

  const activeSignal = signals.find(s => s.pair === activeTf.pair);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 260px', gap: 12 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <GoldLiveChart
            C={C}
            interval={activeTf.interval}
            period={activeTf.period}
            guideSignal={activeSignal}
            onData={setChartData}
            height={480}
            timeframes={TIMEFRAMES}
            activeLabel={activeTf.label}
            onTimeframeChange={setActiveTf}
          />

          {/* Confluence Detail - collapsed by default, expands to show the
              trend/DXY/sub-signal breakdown for whichever timeframe is active */}
          <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 12, overflow: 'hidden' }}>
            <div onClick={() => setDetailOpen(o => !o)} style={{
              cursor: 'pointer', padding: '10px 16px', display: 'flex',
              justifyContent: 'space-between', alignItems: 'center',
            }}>
              <span style={{ color: C.muted, fontSize: 11, letterSpacing: 1 }}>CONFLUENCE DETAIL — {activeTf.label}</span>
              <span style={{ color: C.muted, fontSize: 11 }}>{detailOpen ? '▲ Hide' : '▼ Show'}</span>
            </div>
            {detailOpen && activeSignal && (
              <div style={{ padding: '0 16px 14px' }}>
                {activeSignal.indicators && Object.keys(activeSignal.indicators).length > 0 && (
                  <div style={{ display: 'flex', gap: 14, marginBottom: 8, fontSize: 12 }}>
                    <span style={{ color: C.muted }}>Trend: <span style={{ color: C.text }}>{activeSignal.indicators.trend}</span></span>
                    <span style={{ color: C.muted }}>DXY: <span style={{ color: C.text }}>{activeSignal.indicators.dxy_move}</span></span>
                  </div>
                )}
                {activeSignal.reasons?.map((r, i) => (
                  <div key={i} style={{ color: '#475569', fontSize: 12, lineHeight: 1.6 }}>{r}</div>
                ))}
              </div>
            )}
            {detailOpen && !activeSignal && (
              <div style={{ padding: '0 16px 14px', color: C.dim, fontSize: 12 }}>No signal data yet for {activeTf.label}</div>
            )}
          </div>
        </div>

        <AllSignalsSidebar C={C} />
      </div>

      <GuideHistoryTable C={C} setups={chartData?.setups} guideSignals={chartData?.guide_signals} />
    </div>
  );
}
