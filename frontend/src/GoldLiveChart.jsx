import React, { useEffect, useRef, useState } from 'react';
import { createChart, ColorType } from 'lightweight-charts';

// Live Gold chart, now controlled from OUTSIDE (parent picks the timeframe,
// this just renders it) since the dashboard moved from a 4-panel grid to a
// single chart + sidebar layout. Reports fetched data back up via onData so
// the parent can drive the sidebar highlight, confluence detail strip, and
// combined setups/history table without duplicating the fetch.
//
// Usage: <GoldLiveChart C={C} interval="15m" period="5d" guideSignal={sig} onData={setChartData} />

export default function GoldLiveChart({ C, interval, period, guideSignal, onData, height, timeframes, activeLabel, onTimeframeChange }) {
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

  // Refetch whenever the parent changes interval/period
  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const res = await fetch(`/api/chart/xauusd?interval=${interval}&period=${period}`);
        const json = await res.json();
        if (!cancelled) {
          setData(json);
          if (onData) onData(json);
        }
      } catch (e) {
        if (!cancelled) setError('Could not reach ATLAS chart endpoint');
      }
    }
    load();
    const id = setInterval(load, 60000); // refresh every 60s
    return () => { cancelled = true; clearInterval(id); };
  }, [interval, period]);

  // Render candles + support/resistance + setup/guide markers whenever data updates
  useEffect(() => {
    if (!data || !seriesRef.current || !chartRef.current) return;
    if (!data.candles || data.candles.length === 0) return;

    seriesRef.current.setData(data.candles);

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

    const setupMarkers = (data.setups || []).map(s => ({
      time: s.time,
      position: s.bias === 'bullish' ? 'belowBar' : 'aboveBar',
      color: s.bias === 'bullish' ? C.green : C.red,
      shape: s.bias === 'bullish' ? 'arrowUp' : 'arrowDown',
    }));

    const guideMarkers = (data.guide_signals || []).map(g => ({
      time: g.time,
      position: g.direction === 'BUY' ? 'belowBar' : 'aboveBar',
      color: g.direction === 'BUY' ? C.green : C.red,
      shape: g.direction === 'BUY' ? 'arrowUp' : 'arrowDown',
      size: 2,
      text: `${g.direction} ${g.tier} ${g.price.toFixed(2)}`,
    }));

    const allMarkers = [...setupMarkers, ...guideMarkers].sort((a, b) => a.time - b.time);
    seriesRef.current.setMarkers(allMarkers);
  }, [data]);

  // Nearest support/resistance to current price, for the pill badges
  const nearestSupport = data?.support?.[0];
  const nearestResistance = data?.resistance?.[0];

  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 12, padding: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <span style={{ color: C.text, fontWeight: 700, fontSize: 14 }}>XAU/USD</span>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          {timeframes && timeframes.map(tf => (
            <button key={tf.label} onClick={() => onTimeframeChange && onTimeframeChange(tf)} style={{
              padding: '4px 10px', borderRadius: 6, cursor: 'pointer', fontSize: 11, fontWeight: 700,
              background: activeLabel === tf.label ? '#dbeafe' : 'transparent',
              border: `1px solid ${activeLabel === tf.label ? C.blue + '66' : C.border}`,
              color: activeLabel === tf.label ? C.blue : C.muted,
            }}>{tf.label}</button>
          ))}
          {nearestSupport && (
            <span style={{ background: '#dcfce7', color: C.green, border: `1px solid ${C.green}44`,
              padding: '3px 10px', borderRadius: 20, fontSize: 12, fontWeight: 700 }}>
              SUP {nearestSupport.price.toFixed(2)}
            </span>
          )}
          {nearestResistance && (
            <span style={{ background: '#fee2e2', color: C.red, border: `1px solid ${C.red}44`,
              padding: '3px 10px', borderRadius: 20, fontSize: 12, fontWeight: 700 }}>
              RES {nearestResistance.price.toFixed(2)}
            </span>
          )}
          {data?.current_price && (
            <span style={{ color: C.gold, fontFamily: 'JetBrains Mono', fontWeight: 700 }}>{data.current_price.toFixed(2)}</span>
          )}
        </div>
      </div>

      {error && <div style={{ color: C.red, fontSize: 13, marginBottom: 8 }}>{error}</div>}
      <div ref={containerRef} />
    </div>
  );
}
