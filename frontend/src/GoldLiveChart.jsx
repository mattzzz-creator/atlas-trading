import React, { useEffect, useRef, useState } from 'react';
import { createChart, ColorType } from 'lightweight-charts';

// Live Gold chart with server-detected support/resistance levels and
// candlestick "setups" (pattern + level together) drawn automatically -
// nothing is drawn by hand, it all comes from /api/chart/xauusd.
//
// Requires: npm install lightweight-charts
//
// Usage: <GoldLiveChart C={C} guideSignal={guideSignal} />
// guideSignal is the "XAUUSD-GUIDE" entry from App.jsx's signals state -
// passing it in surfaces the same trend/DXY/tier info the TradingView
// version shows, right next to the chart instead of hidden behind a click.

const TIMEFRAMES = [
  { label: '1m',  interval: '1m',  period: '7d' },   // Yahoo's hard limit for 1m data
  { label: '5m',  interval: '5m',  period: '2d' },
  { label: '15m', interval: '15m', period: '5d' },
  { label: '30m', interval: '30m', period: '10d' },
];

export default function GoldLiveChart({ C, guideSignal, defaultTf, height, lockTf }) {
  const containerRef = useRef(null);
  const chartRef = useRef(null);
  const seriesRef = useRef(null);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const initialTf = TIMEFRAMES.find(t => t.label === defaultTf) || TIMEFRAMES[1];
  const [tf, setTf] = useState(initialTf); // default 15m unless defaultTf given

  // Create the chart once
  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      layout: { background: { type: ColorType.Solid, color: C.card }, textColor: C.text },
      grid: { vertLines: { color: C.border }, horzLines: { color: C.border } },
      width: containerRef.current.clientWidth,
      height: height || 480,
      timeScale: { timeVisible: true, secondsVisible: false },
    });
    const series = chart.addCandlestickSeries({
      upColor: C.green, downColor: C.red,
      borderVisible: false,
      wickUpColor: C.green, wickDownColor: C.red,
    });
    chartRef.current = chart;
    seriesRef.current = series;

    const handleResize = () => chart.applyOptions({ width: containerRef.current.clientWidth });
    window.addEventListener('resize', handleResize);
    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, []);

  // Poll the backend - refetches whenever the chosen timeframe changes
  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const res = await fetch(`/api/chart/xauusd?interval=${tf.interval}&period=${tf.period}`);
        const json = await res.json();
        if (!cancelled) setData(json);
      } catch (e) {
        if (!cancelled) setError('Could not reach ATLAS chart endpoint');
      }
    }
    load();
    const id = setInterval(load, 60000); // refresh every 60s
    return () => { cancelled = true; clearInterval(id); };
  }, [tf]);

  // Render candles + support/resistance + setup markers whenever data updates
  useEffect(() => {
    if (!data || !seriesRef.current || !chartRef.current) return;
    if (!data.candles || data.candles.length === 0) return;

    seriesRef.current.setData(data.candles);

    // Clear old price lines by re-adding the series' price lines fresh each time
    (seriesRef.current._priceLines || []).forEach(pl => seriesRef.current.removePriceLine(pl));
    seriesRef.current._priceLines = [];

    (data.support || []).slice(0, 2).forEach(lv => {
      const pl = seriesRef.current.createPriceLine({
        price: lv.price, color: C.green, lineWidth: 1, lineStyle: 2,
        axisLabelVisible: true, title: `Support (${lv.touches}x)`,
      });
      seriesRef.current._priceLines.push(pl);
    });

    (data.resistance || []).slice(0, 2).forEach(lv => {
      const pl = seriesRef.current.createPriceLine({
        price: lv.price, color: C.red, lineWidth: 1, lineStyle: 2,
        axisLabelVisible: true, title: `Resistance (${lv.touches}x)`,
      });
      seriesRef.current._priceLines.push(pl);
    });

    const markers = (data.setups || []).map(s => ({
      time: s.time,
      position: s.bias === 'bullish' ? 'belowBar' : 'aboveBar',
      color: s.bias === 'bullish' ? C.green : C.red,
      shape: s.bias === 'bullish' ? 'arrowUp' : 'arrowDown',
      // No text on the marker itself - long strings stacked close in time
      // just overlap into an unreadable mess. The list below the chart
      // shows the actual labels instead.
    }));
    seriesRef.current.setMarkers(markers);
  }, [data]);

  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 12, padding: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <span style={{ color: C.text, fontWeight: 700, fontSize: 14 }}>XAU/USD {lockTf ? `— ${tf.label}` : '— Live Chart'}</span>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          {!lockTf && TIMEFRAMES.map(t => (
            <button key={t.label} onClick={() => setTf(t)} style={{
              padding: '4px 10px', borderRadius: 6, cursor: 'pointer', fontSize: 11, fontWeight: 600,
              background: tf.label === t.label ? '#1e2d45' : 'transparent',
              border: `1px solid ${tf.label === t.label ? C.blue + '66' : C.border}`,
              color: tf.label === t.label ? C.blue : C.muted,
            }}>{t.label}</button>
          ))}
          {data?.current_price && (
            <span style={{ color: C.gold, fontFamily: 'JetBrains Mono', marginLeft: 8 }}>{data.current_price.toFixed(2)}</span>
          )}
        </div>
      </div>

      {/* Guide signal HUD - same info the TradingView dashboard shows, from
          the XAUUSD-GUIDE signal ATLAS already generates every 3 minutes */}
      {guideSignal && (
        <div style={{ background: '#060609', border: `1px solid ${C.border}`, borderRadius: 8,
          padding: '10px 12px', marginBottom: 10 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
            <span style={{ color: C.muted, fontSize: 10, letterSpacing: 2 }}>MANUAL GUIDE STATUS</span>
            <span style={{
              color: guideSignal.direction === 'BUY' ? C.green : guideSignal.direction === 'SELL' ? C.red : C.muted,
              fontWeight: 800, fontSize: 12,
            }}>
              {guideSignal.direction !== 'HOLD' ? `${guideSignal.direction} · ${guideSignal.strength}` : 'WAIT'}
            </span>
          </div>
          {guideSignal.indicators && Object.keys(guideSignal.indicators).length > 0 && (
            <div style={{ display: 'flex', gap: 14, marginBottom: 6, fontSize: 11 }}>
              <span style={{ color: C.muted }}>Trend: <span style={{ color: C.text }}>{guideSignal.indicators.trend}</span></span>
              <span style={{ color: C.muted }}>DXY: <span style={{ color: C.text }}>{guideSignal.indicators.dxy_move}</span></span>
            </div>
          )}
          {guideSignal.reasons?.map((r, i) => (
            <div key={i} style={{ color: '#94a3b8', fontSize: 11, lineHeight: 1.5 }}>{r}</div>
          ))}
        </div>
      )}

      {error && <div style={{ color: C.red, fontSize: 13, marginBottom: 8 }}>{error}</div>}
      <div ref={containerRef} />
      {data?.setups?.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <div style={{ color: C.muted, fontSize: 10, letterSpacing: 2, marginBottom: 6 }}>RECENT SETUPS</div>
          {data.setups.slice(-6).reverse().map((s, i) => (
            <div key={`${s.time}-${s.label}`} style={{
              display: 'flex', justifyContent: 'space-between',
              color: s.bias === 'bullish' ? C.green : C.red,
              fontSize: 13, padding: '4px 0', borderTop: `1px solid ${C.border}`,
            }}>
              <span>{s.label}</span>
              <span>{s.price.toFixed(2)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
