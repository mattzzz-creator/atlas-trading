import React from 'react';
import GoldLiveChart from './GoldLiveChart.jsx';

// Four independent Gold charts side by side, one per timeframe (M5, M15,
// H1, D1), each wired to its OWN signal (XAUUSD-GUIDE-M5 etc) - not the
// same signal relabeled four times. Each timeframe has genuinely different
// confluence because the underlying HTF/trend references scale with it.

const PANELS = [
  { tf: '1m',  pair: 'XAUUSD-GUIDE-M1'  },
  { tf: '5m',  pair: 'XAUUSD-GUIDE-M5'  },
  { tf: '15m', pair: 'XAUUSD-GUIDE-M15' },
  { tf: '30m', pair: 'XAUUSD-GUIDE-M30' },
];

export default function GoldMultiTimeframeGrid({ C, signals }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
      {PANELS.map(p => (
        <GoldLiveChart
          key={p.pair}
          C={C}
          defaultTf={p.tf}
          lockTf={true}
          height={260}
          guideSignal={signals.find(s => s.pair === p.pair)}
        />
      ))}
    </div>
  );
}
