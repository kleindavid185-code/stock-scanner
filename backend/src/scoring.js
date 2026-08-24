// Scores candidates using observable momentum/volatility signals.
//
// This is a *screener*, not a predictor: it surfaces stocks currently
// showing the kind of behavior (volume surge, big % move, wide range)
// that often precedes or accompanies a spike. It does not forecast the
// future and should not be read as one. Think "better Finviz/Trade Ideas
// scan," not "AI knows what's about to skyrocket."

import { priceActionFlags } from "../signal-engine/indicators.js";
import { MEGA_CAP_EXCLUDED } from "./megaCapExclusions.js";

const MIN_PRICE = 5; // the only hard cutoff -- below this, spreads/quotes get too noisy to trust
const EXTREME_RVOL = 200; // above this, RVOL usually means thin/broken data -- flagged, not excluded
const BAD_DATA_CHANGE_PCT = -90; // a -90%+ move (like the MSAIW -99% case) is almost always delisted/halted/broken data, not real price action

function pctChange(from, to) {
  if (!from) return 0;
  return ((to - from) / from) * 100;
}

// Very rough relative-volume proxy: today's volume so far vs. yesterday's
// full-day volume. A true intraday-time-adjusted RVOL needs an average
// volume-by-minute baseline; this is a fast first pass.
function relativeVolume(dailyBar, prevDailyBar) {
  if (!prevDailyBar?.v) return 1;
  return dailyBar.v / prevDailyBar.v;
}

/**
 * Scores one symbol's snapshot. Hard exclusions: price (MIN_PRICE),
 * obviously-broken data (BAD_DATA_CHANGE_PCT), and mega-cap stocks/broad
 * ETFs (MEGA_CAP_EXCLUDED) that don't fit a low-float momentum style
 * regardless of how their RVOL/momentum/trend look. Everything else (RVOL,
 * momentum, range, trend) affects rank/flags, not whether a candidate
 * appears at all, so the list stays broad. Returns null if the symbol
 * should be excluded entirely. Does NOT classify trend -- that needs
 * historical bars, fetched separately (see rankCandidates below) only for
 * symbols that survive these cheap filters.
 */
export function scoreSnapshot(symbol, snap) {
  const daily = snap.dailyBar;
  const prevDaily = snap.prevDailyBar;
  const trade = snap.latestTrade;

  if (!daily || !prevDaily || !trade) return null;
  if (MEGA_CAP_EXCLUDED.has(symbol)) return null;

  const price = trade.p;
  const changePct = pctChange(prevDaily.c, price);
  const rvol = relativeVolume(daily, prevDaily);
  const rangePct = daily.h && daily.l ? pctChange(daily.l, daily.h) : 0;
  const gapPct = pctChange(prevDaily.c, daily.o);

  if (price < MIN_PRICE) return null;
  // Extreme crashes are almost always broken/delisted/halted data (a real
  // -90%+ single-day move without a halt is vanishingly rare) -- exclude
  // rather than let them dominate the "biggest movers" ranking.
  if (changePct <= BAD_DATA_CHANGE_PCT || gapPct <= BAD_DATA_CHANGE_PCT) return null;

  // RVOL this extreme is more often a thin/illiquid symbol producing a
  // noisy volume ratio than a genuine surge -- keep it, but flag it as
  // low-confidence rather than silently ranking it like a normal result.
  const lowConfidence = rvol > EXTREME_RVOL;

  // Simple weighted composite. Tune freely -- these weights just express
  // "volume surge matters most, then momentum, then intraday range/gap."
  const score =
    Math.min(rvol, 10) * 4 +
    Math.min(Math.abs(changePct), 50) * 1.2 +
    Math.min(rangePct, 50) * 0.6 +
    Math.min(Math.abs(gapPct), 30) * 0.5;

  return {
    symbol,
    price,
    changePct: round(changePct),
    rvol: round(rvol),
    rangePct: round(rangePct),
    gapPct: round(gapPct),
    volume: daily.v,
    score: round(score),
    lowConfidence,
  };
}

function round(n) {
  return Math.round(n * 100) / 100;
}

/**
 * Classifies a scored candidate's trend from its historical daily bars
 * (oldest-first) using indicators.js's existing priceActionFlags(). Missing
 * or insufficient bars just means "unknown trend" -- the candidate still
 * ranks, just without the trend-priority boost.
 */
function classifyTrend(candidate, bars) {
  if (!bars || !bars.length) return { ...candidate, trend: null };
  const { flags } = priceActionFlags(bars);
  const trend = flags.includes("uptrend")
    ? "uptrend"
    : flags.includes("downtrend")
      ? "downtrend"
      : "choppy";
  return { ...candidate, trend };
}

/**
 * Filters snapshots down to viable candidates, classifies each survivor's
 * trend from `barsBySymbol` (symbol -> daily bars, oldest-first), and sorts
 * clear uptrend/downtrend names above choppy/unknown ones -- trending
 * stocks matter more for this trading style than random noise -- with the
 * existing composite score breaking ties within each group.
 */
export function rankCandidates(snapshots, barsBySymbol = {}) {
  const scored = Object.entries(snapshots)
    .map(([symbol, snap]) => scoreSnapshot(symbol, snap))
    .filter(Boolean)
    .map((candidate) => classifyTrend(candidate, barsBySymbol[candidate.symbol]));

  scored.sort((a, b) => {
    const aTrending = a.trend === "uptrend" || a.trend === "downtrend" ? 1 : 0;
    const bTrending = b.trend === "uptrend" || b.trend === "downtrend" ? 1 : 0;
    if (aTrending !== bTrending) return bTrending - aTrending;
    return b.score - a.score;
  });

  return scored;
}
