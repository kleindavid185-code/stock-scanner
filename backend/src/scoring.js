// Scores candidates using observable momentum/volatility signals.
//
// This is a *screener*, not a predictor: it surfaces stocks currently
// showing the kind of behavior (volume surge, big % move, wide range)
// that often precedes or accompanies a spike. It does not forecast the
// future and should not be read as one. Think "better Finviz/Trade Ideas
// scan," not "AI knows what's about to skyrocket."

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

export function scoreSnapshot(symbol, snap) {
  const daily = snap.dailyBar;
  const prevDaily = snap.prevDailyBar;
  const trade = snap.latestTrade;

  if (!daily || !prevDaily || !trade) return null;

  const price = trade.p;
  const changePct = pctChange(prevDaily.c, price);
  const rvol = relativeVolume(daily, prevDaily);
  const rangePct = daily.h && daily.l ? pctChange(daily.l, daily.h) : 0;
  const gapPct = pctChange(prevDaily.c, daily.o);

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
  };
}

function round(n) {
  return Math.round(n * 100) / 100;
}

export function rankCandidates(snapshots) {
  const scored = Object.entries(snapshots)
    .map(([symbol, snap]) => scoreSnapshot(symbol, snap))
    .filter(Boolean);
  scored.sort((a, b) => b.score - a.score);
  return scored;
}
