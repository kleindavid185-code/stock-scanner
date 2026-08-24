/**
 * indicators.js
 * Pure functions for computing technical indicators from OHLCV bar data.
 * Expects bars as an array of objects, oldest first:
 *   { t: timestamp, o: open, h: high, l: low, c: close, v: volume }
 * This matches Alpaca's bar shape closely enough that you can map
 * Alpaca bars -> this shape with a one-line .map() in your data layer.
 */

function toCloses(bars) {
  return bars.map((b) => b.c);
}

/** Simple moving average over the last `period` closes. */
function sma(values, period) {
  if (values.length < period) return null;
  const slice = values.slice(-period);
  return slice.reduce((a, b) => a + b, 0) / period;
}

/** Exponential moving average series (returns full array, same length as input). */
function emaSeries(values, period) {
  if (values.length === 0) return [];
  const k = 2 / (period + 1);
  const out = [values[0]];
  for (let i = 1; i < values.length; i++) {
    out.push(values[i] * k + out[i - 1] * (1 - k));
  }
  return out;
}

/** Latest EMA value for a given period. */
function ema(values, period) {
  const series = emaSeries(values, period);
  return series.length ? series[series.length - 1] : null;
}

/**
 * RSI (Wilder's smoothing), returns a value 0-100 or null if not enough data.
 */
function rsi(bars, period = 14) {
  const closes = toCloses(bars);
  if (closes.length < period + 1) return null;

  let gains = 0;
  let losses = 0;
  for (let i = 1; i <= period; i++) {
    const diff = closes[i] - closes[i - 1];
    if (diff >= 0) gains += diff;
    else losses -= diff;
  }
  let avgGain = gains / period;
  let avgLoss = losses / period;

  for (let i = period + 1; i < closes.length; i++) {
    const diff = closes[i] - closes[i - 1];
    const gain = diff > 0 ? diff : 0;
    const loss = diff < 0 ? -diff : 0;
    avgGain = (avgGain * (period - 1) + gain) / period;
    avgLoss = (avgLoss * (period - 1) + loss) / period;
  }

  if (avgLoss === 0) return 100;
  const rs = avgGain / avgLoss;
  return 100 - 100 / (1 + rs);
}

/**
 * MACD: returns { macd, signal, histogram } using standard 12/26/9 periods.
 */
function macd(bars, fast = 12, slow = 26, signalPeriod = 9) {
  const closes = toCloses(bars);
  if (closes.length < slow + signalPeriod) return null;

  const fastEma = emaSeries(closes, fast);
  const slowEma = emaSeries(closes, slow);
  const macdLine = closes.map((_, i) => fastEma[i] - slowEma[i]);
  const signalLine = emaSeries(macdLine, signalPeriod);

  const last = macdLine.length - 1;
  return {
    macd: Number(macdLine[last].toFixed(4)),
    signal: Number(signalLine[last].toFixed(4)),
    histogram: Number((macdLine[last] - signalLine[last]).toFixed(4)),
  };
}

/**
 * VWAP for the bars provided (typically pass only today's intraday bars —
 * VWAP conventionally resets each session).
 */
function vwap(bars) {
  if (!bars.length) return null;
  let cumPV = 0;
  let cumVol = 0;
  for (const b of bars) {
    const typicalPrice = (b.h + b.l + b.c) / 3;
    cumPV += typicalPrice * b.v;
    cumVol += b.v;
  }
  if (cumVol === 0) return null;
  return Number((cumPV / cumVol).toFixed(4));
}

/**
 * ATR (Average True Range), Wilder smoothing, default 14-period.
 */
function atr(bars, period = 14) {
  if (bars.length < period + 1) return null;
  const trueRanges = [];
  for (let i = 1; i < bars.length; i++) {
    const cur = bars[i];
    const prevClose = bars[i - 1].c;
    const tr = Math.max(
      cur.h - cur.l,
      Math.abs(cur.h - prevClose),
      Math.abs(cur.l - prevClose)
    );
    trueRanges.push(tr);
  }
  let atrVal = trueRanges.slice(0, period).reduce((a, b) => a + b, 0) / period;
  for (let i = period; i < trueRanges.length; i++) {
    atrVal = (atrVal * (period - 1) + trueRanges[i]) / period;
  }
  return Number(atrVal.toFixed(4));
}

/**
 * Average day-over-day close change (signed) over the last `period` bars —
 * used as a simple "typical drift" to project tomorrow's anchor price.
 * Not a prediction of direction, just the recent trend's average daily move.
 */
function averageDailyDrift(bars, period = 14) {
  if (bars.length < period + 1) return 0;
  const recent = bars.slice(-(period + 1));
  let sum = 0;
  for (let i = 1; i < recent.length; i++) {
    sum += recent[i].c - recent[i - 1].c;
  }
  return sum / (recent.length - 1);
}

/**
 * Expected trading range, derived from ATR(14) — a statistical volatility
 * estimate, not a price prediction. Today's range is currentPrice ± ATR.
 *
 * Tomorrow's range can't just reuse currentPrice ± ATR: the midpoint of a
 * symmetric ATR band is currentPrice itself, so that anchor never moves.
 * Instead we project tomorrow's anchor as currentPrice + the recent average
 * daily drift (the typical day-over-day close change over the same lookback
 * as ATR), then apply the same ATR band around that projected close.
 */
function expectedRange(bars, period = 14) {
  if (!bars.length) return null;
  const atrVal = atr(bars, period);
  if (atrVal == null) return null;

  const currentPrice = bars[bars.length - 1].c;
  const drift = averageDailyDrift(bars, period);
  const projectedClose = Number((currentPrice + drift).toFixed(2));

  return {
    today: {
      low: Number((currentPrice - atrVal).toFixed(2)),
      high: Number((currentPrice + atrVal).toFixed(2)),
    },
    tomorrow: {
      low: Number((projectedClose - atrVal).toFixed(2)),
      high: Number((projectedClose + atrVal).toFixed(2)),
    },
  };
}

/**
 * Relative volume: current bar volume (or sum of today's bars so far)
 * vs. the average volume for the same period across `lookbackDays`.
 * avgBaselineVolume should be precomputed by your data layer
 * (e.g. average of the last 10 days' volume-to-this-time-of-day).
 */
function relativeVolume(currentVolume, avgBaselineVolume) {
  if (!avgBaselineVolume) return null;
  return Number((currentVolume / avgBaselineVolume).toFixed(2));
}

/**
 * Lightweight price-action classifier — not a substitute for real pattern
 * recognition, but gives the AI layer useful structured hints.
 * Looks at the last `window` bars.
 */
function priceActionFlags(bars, window = 20) {
  if (bars.length < window) return { flags: [], note: "insufficient data" };

  const recent = bars.slice(-window);
  const highs = recent.map((b) => b.h);
  const lows = recent.map((b) => b.l);
  const closes = recent.map((b) => b.c);

  const rangeHigh = Math.max(...highs);
  const rangeLow = Math.min(...lows);
  const lastClose = closes[closes.length - 1];
  const firstClose = closes[0];

  const flags = [];

  // Breakout: closing within 1% of the recent range high
  if (lastClose >= rangeHigh * 0.99) flags.push("near_range_high_breakout");
  if (lastClose <= rangeLow * 1.01) flags.push("near_range_low_breakdown");

  // Tight consolidation: range is small relative to price
  const rangePct = (rangeHigh - rangeLow) / firstClose;
  if (rangePct < 0.03) flags.push("tight_consolidation");

  // Trend direction over the window
  const changePct = (lastClose - firstClose) / firstClose;
  if (changePct > 0.02) flags.push("uptrend");
  else if (changePct < -0.02) flags.push("downtrend");
  else flags.push("choppy");

  return { flags, rangeHigh, rangeLow, changePct: Number((changePct * 100).toFixed(2)) };
}

/**
 * Convenience: compute the full indicator bundle for one symbol's bars.
 * `sessionBars` should be just today's intraday bars (for VWAP).
 * `avgBaselineVolume` is optional, precomputed elsewhere.
 */
function computeIndicatorBundle(bars, sessionBars = bars, avgBaselineVolume = null) {
  const currentVolume = sessionBars.reduce((sum, b) => sum + b.v, 0);
  return {
    price: bars.length ? bars[bars.length - 1].c : null,
    rsi14: rsi(bars, 14),
    macd: macd(bars),
    vwap: vwap(sessionBars),
    atr14: atr(bars, 14),
    expectedRange: expectedRange(bars, 14),
    relativeVolume: relativeVolume(currentVolume, avgBaselineVolume),
    priceAction: priceActionFlags(bars),
  };
}

export {
  sma,
  ema,
  emaSeries,
  rsi,
  macd,
  vwap,
  atr,
  expectedRange,
  relativeVolume,
  priceActionFlags,
  computeIndicatorBundle,
};
