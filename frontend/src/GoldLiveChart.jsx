import React, { useEffect, useRef, useState } from 'react';
import { createChart, ColorType } from 'lightweight-charts';

// Live Gold chart with server-detected support/resistance levels and
// candlestick "setups" (pattern + level together) drawn automatically -
// nothing is drawn by hand, it all comes from /api/chart/xauusd.
//
// Requires: npm install lightweight-charts
//
// Usage: <GoldLiveChart C={C} />  (pass your existing color palette object
// from App.jsx so this matches the rest of the dashboard exactly)

export default function GoldLiveChart({ C }) {
  const containerRef = useRef(null);
  const chartRef = useRef(null);
  const seriesRef = useRef(null);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  // Create the chart once
  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      layout: { background: { type: ColorType.Solid, color: C.card }, textColor: C.text },
      grid: { vertLines: { color: C.border }, horzLines: { color: C.border } },
      width: containerRef.current.clientWidth,
      height: 480,
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

  // Poll the backend
  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const res = await fetch(`/api/chart/xauusd?interval=15m&period=5d`);
        const json = await res.json();
        if (!cancelled) setData(json);
      } catch (e) {
        if (!cancelled) setError('Could not reach ATLAS chart endpoint');
      }
    }
    load();
    const id = setInterval(load, 60000); // refresh every 60s
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  // Render candles + support/resistance + setup markers whenever data updates
  useEffect(() => {
    if (!data || !seriesRef.current || !chartRef.current) return;
    if (!data.candles || data.candles.length === 0) return;

    seriesRef.current.setData(data.candles);

    // Clear old price lines by re-adding the series' price lines fresh each time
    (seriesRef.current._priceLines || []).forEach(pl => seriesRef.current.removePriceLine(pl));
    seriesRef.current._priceLines = [];

    (data.support || []).forEach(lv => {
      const pl = seriesRef.current.createPriceLine({
        price: lv.price, color: C.green, lineWidth: 1, lineStyle: 2,
        axisLabelVisible: true, title: `Support (${lv.touches}x)`,
      });
      seriesRef.current._priceLines.push(pl);
    });

    (data.resistance || []).forEach(lv => {
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
      text: s.label,
    }));
    seriesRef.current.setMarkers(markers);
  }, [data]);

  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 12, padding: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
        <span style={{ color: C.text, fontWeight: 700, fontSize: 14 }}>XAU/USD — Live Chart</span>
        {data?.current_price && (
          <span style={{ color: C.gold, fontFamily: 'JetBrains Mono' }}>{data.current_price.toFixed(2)}</span>
        )}
      </div>
      {error && <div style={{ color: C.red, fontSize: 13, marginBottom: 8 }}>{error}</div>}
      <div ref={containerRef} />
      {data?.setups?.length > 0 && (
        <div style={{ marginTop: 12 }}>
          {data.setups.map((s, i) => (
            <div key={i} style={{
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
