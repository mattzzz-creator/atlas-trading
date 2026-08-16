import React, { useEffect, useState } from 'react';

// Live feed of fired signals across ALL 4 timeframes - a scrolling list,
// like the reference design's sidebar, not a static per-timeframe picker.
// Timeframe switching now lives as tabs on the chart itself instead.

export default function AllSignalsSidebar({ C }) {
  const [feed, setFeed] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const res = await fetch('/api/gold-guide/feed');
        const json = await res.json();
        if (!cancelled) setFeed(json.feed || []);
      } catch (e) {
        if (!cancelled) setError('Could not reach ATLAS feed endpoint');
      }
    }
    load();
    const id = setInterval(load, 60000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 12, padding: 12, display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 560, overflowY: 'auto' }}>
      <div style={{ color: C.muted, fontSize: 10, letterSpacing: 2, padding: '4px 4px 8px' }}>ALL SIGNALS</div>
      {error && <div style={{ color: C.red, fontSize: 12, padding: '4px' }}>{error}</div>}
      {feed.length === 0 && !error && (
        <div style={{ color: C.dim, fontSize: 12, padding: '4px' }}>No signals fired yet across any timeframe</div>
      )}
      {feed.map((g, i) => {
        const dc = g.direction === 'BUY' ? C.green : C.red;
        const time = new Date(g.time * 1000);
        const timeStr = time.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
        return (
          <div key={`${g.time}-${g.timeframe}-${i}`} style={{
            borderRadius: 8, padding: '10px 12px', border: `1px solid ${C.border}`,
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 3 }}>
              <span style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <span style={{ background: '#dbeafe', color: C.blue, fontSize: 10, fontWeight: 700,
                  padding: '2px 6px', borderRadius: 4 }}>{g.timeframe}</span>
                <span style={{ color: dc, fontWeight: 700, fontSize: 13 }}>{g.direction}</span>
              </span>
              <span style={{ color: C.text, fontFamily: 'JetBrains Mono', fontSize: 12 }}>{g.price.toFixed(2)}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10 }}>
              <span style={{ color: C.muted }}>{g.tier}</span>
              <span style={{ color: C.dim }}>{timeStr}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
