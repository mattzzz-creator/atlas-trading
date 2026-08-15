import React from 'react';

// Two-column table below the chart - candlestick setups on the left,
// confluence-engine BUY/SELL history on the right. Replaces the two
// separate stacked lists the 4-panel version had, matching the reference
// design's two-column trade-history layout.

export default function GuideHistoryTable({ C, setups, guideSignals }) {
  const hasAny = (setups && setups.length > 0) || (guideSignals && guideSignals.length > 0);
  if (!hasAny) return null;

  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 12, padding: 16 }}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
        <div>
          <div style={{ color: C.muted, fontSize: 10, letterSpacing: 2, marginBottom: 8 }}>RECENT SETUPS</div>
          {(setups || []).slice(-8).reverse().map((s, i) => (
            <div key={`${s.time}-${i}`} style={{
              display: 'flex', justifyContent: 'space-between',
              color: s.bias === 'bullish' ? C.green : C.red,
              fontSize: 13, padding: '6px 0', borderTop: `1px solid ${C.border}`,
            }}>
              <span>{s.label}</span>
              <span>{s.price.toFixed(2)}</span>
            </div>
          ))}
          {(!setups || setups.length === 0) && (
            <div style={{ color: C.dim, fontSize: 12, padding: '6px 0' }}>No setups detected yet</div>
          )}
        </div>
        <div>
          <div style={{ color: C.muted, fontSize: 10, letterSpacing: 2, marginBottom: 8 }}>GUIDE SIGNAL HISTORY</div>
          {(guideSignals || []).slice(-8).reverse().map((g, i) => (
            <div key={`${g.time}-${i}`} style={{
              display: 'flex', justifyContent: 'space-between',
              color: g.direction === 'BUY' ? C.green : C.red,
              fontSize: 13, padding: '6px 0', borderTop: `1px solid ${C.border}`,
            }}>
              <span>{g.direction} · {g.tier}</span>
              <span>{g.price.toFixed(2)}</span>
            </div>
          ))}
          {(!guideSignals || guideSignals.length === 0) && (
            <div style={{ color: C.dim, fontSize: 12, padding: '6px 0' }}>No confluence signals in this window yet</div>
          )}
        </div>
      </div>
    </div>
  );
}
