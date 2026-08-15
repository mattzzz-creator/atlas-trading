import React from 'react';

// Sidebar list of all 4 timeframe signals at once, like the currency-pair
// list in the reference design - click a row to switch the main chart to
// that timeframe. The active timeframe is highlighted.

const TIMEFRAMES = [
  { label: 'M1',  interval: '1m',  period: '7d',  pair: 'XAUUSD-GUIDE-M1'  },
  { label: 'M5',  interval: '5m',  period: '2d',  pair: 'XAUUSD-GUIDE-M5'  },
  { label: 'M15', interval: '15m', period: '5d',  pair: 'XAUUSD-GUIDE-M15' },
  { label: 'M30', interval: '30m', period: '10d', pair: 'XAUUSD-GUIDE-M30' },
];

export { TIMEFRAMES };

export default function AllSignalsSidebar({ C, signals, activeInterval, onSelect }) {
  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 12, padding: 12, display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div style={{ color: C.muted, fontSize: 10, letterSpacing: 2, padding: '4px 4px 8px' }}>ALL SIGNALS</div>
      {TIMEFRAMES.map(tf => {
        const sig = signals.find(s => s.pair === tf.pair);
        const dir = sig?.direction || 'WAIT';
        const isActive = tf.interval === activeInterval;
        const dc = dir === 'BUY' ? C.green : dir === 'SELL' ? C.red : C.muted;

        return (
          <div key={tf.pair} onClick={() => onSelect(tf)} style={{
            cursor: 'pointer', borderRadius: 8, padding: '10px 12px',
            background: isActive ? '#1e2d45' : 'transparent',
            border: `1px solid ${isActive ? C.blue + '66' : C.border}`,
            transition: 'all 0.15s',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 3 }}>
              <span style={{ color: isActive ? C.blue : C.text, fontWeight: 700, fontSize: 13 }}>{tf.label}</span>
              <span style={{ color: dc, fontWeight: 700, fontSize: 12 }}>
                {dir !== 'WAIT' && dir !== 'HOLD' ? `${dir} · ${sig.strength}` : 'WAIT'}
              </span>
            </div>
            {sig?.indicators?.trend && (
              <div style={{ color: C.muted, fontSize: 10 }}>
                Trend: {sig.indicators.trend}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
