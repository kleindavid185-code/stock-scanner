/**
 * alpacaData.js
 * Fetches OHLCV bars from Alpaca's Market Data API (IEX free-tier feed)
 * and shapes them for indicators.js / signalRoute.js.
 *
 * Env vars required (matches src/alpacaClient.js's existing convention):
 *   ALPACA_API_KEY
 *   ALPACA_API_SECRET
 *
 * Docs: https://docs.alpaca.markets/reference/stockbars
 */

const BASE_URL = "https://data.alpaca.markets/v2";
const FEED = process.env.ALPACA_DATA_FEED || "iex";

function authHeaders() {
  const keyId = process.env.ALPACA_API_KEY;
  const secretKey = process.env.ALPACA_API_SECRET;
  if (!keyId || !secretKey) {
    throw new Error(
      "Missing ALPACA_API_KEY / ALPACA_API_SECRET. Copy .env.example to .env and fill in your keys."
    );
  }
  return {
    "APCA-API-KEY-ID": keyId,
    "APCA-API-SECRET-KEY": secretKey,
  };
}

/**
 * Low-level fetch with retry on 429 (rate limit) and transient 5xx errors.
 */
async function fetchWithRetry(url, options, retries = 3, backoffMs = 500) {
  for (let attempt = 0; attempt <= retries; attempt++) {
    const res = await fetch(url, options);

    if (res.ok) return res.json();

    // Rate limited — back off and retry
    if (res.status === 429 && attempt < retries) {
      await new Promise((r) => setTimeout(r, backoffMs * (attempt + 1)));
      continue;
    }

    // Transient server error — retry
    if (res.status >= 500 && attempt < retries) {
      await new Promise((r) => setTimeout(r, backoffMs * (attempt + 1)));
      continue;
    }

    const body = await res.text().catch(() => "");
    throw new Error(`Alpaca request failed (${res.status}): ${body}`);
  }
}

/**
 * Pulls raw bars for a symbol/timeframe/date range, following pagination
 * (Alpaca returns a next_page_token when there's more data).
 */
async function getRawBars(symbol, { timeframe, start, end, limit = 1000 }) {
  const allBars = [];
  let pageToken = null;

  do {
    const params = new URLSearchParams({
      timeframe,
      start,
      end,
      limit: String(limit),
      feed: FEED,
      adjustment: "raw",
    });
    if (pageToken) params.set("page_token", pageToken);

    const url = `${BASE_URL}/stocks/${symbol}/bars?${params.toString()}`;
    const data = await fetchWithRetry(url, { headers: authHeaders() });

    if (data.bars) allBars.push(...data.bars);
    pageToken = data.next_page_token || null;
  } while (pageToken);

  return allBars;
}

/** Maps Alpaca's { t, o, h, l, c, v } bar shape to indicators.js's expected shape. */
function mapBar(b) {
  return {
    t: b.t, // ISO timestamp string
    o: b.o,
    h: b.h,
    l: b.l,
    c: b.c,
    v: b.v,
  };
}

function isoDate(d) {
  return d.toISOString().slice(0, 10);
}

/**
 * Fetches everything signalRoute.js needs for one symbol:
 *   - intraday: today's 1-minute bars (for VWAP + current session context)
 *   - daily: recent daily bars (for RSI/MACD/ATR, which need real history)
 *   - avgBaselineVolume: average total daily volume over the last N days,
 *     used as the denominator for relative volume
 *
 * This is the function signalRoute.js imports and calls per symbol.
 */
async function fetchBarsForSymbol(symbol, opts = {}) {
  const {
    dailyLookbackDays = 60, // enough history for RSI(14)/MACD(26)/ATR(14)
    baselineVolumeDays = 10,
  } = opts;

  const now = new Date();
  const dailyStart = new Date(now);
  dailyStart.setDate(dailyStart.getDate() - dailyLookbackDays);

  const todayStart = new Date(now);
  todayStart.setHours(0, 0, 0, 0);

  const [rawDaily, rawIntraday] = await Promise.all([
    getRawBars(symbol, {
      timeframe: "1Day",
      start: isoDate(dailyStart),
      end: isoDate(now),
    }),
    getRawBars(symbol, {
      timeframe: "1Min",
      start: todayStart.toISOString(),
      end: now.toISOString(),
    }),
  ]);

  const daily = rawDaily.map(mapBar);
  const intraday = rawIntraday.map(mapBar);

  // Baseline volume: average of the last N complete daily bars (excluding
  // today, since today's bar is still in progress and would skew it low).
  const completeDailyVolumes = daily
    .filter((b) => b.t.slice(0, 10) !== isoDate(now))
    .slice(-baselineVolumeDays)
    .map((b) => b.v);

  const avgBaselineVolume =
    completeDailyVolumes.length > 0
      ? completeDailyVolumes.reduce((a, b) => a + b, 0) / completeDailyVolumes.length
      : null;

  return { intraday, daily, avgBaselineVolume };
}

/**
 * Optional: simple in-memory cache so a busy polling loop doesn't refetch
 * daily history every single tick — daily bars only need refreshing once
 * per session, only intraday needs to be fresh every poll.
 */
const dailyCache = new Map(); // symbol -> { date: 'YYYY-MM-DD', bars: [...] }

async function fetchBarsForSymbolCached(symbol, opts = {}) {
  const today = isoDate(new Date());
  const cached = dailyCache.get(symbol);

  const [rawIntraday] = await Promise.all([
    (async () => {
      const now = new Date();
      const todayStart = new Date(now);
      todayStart.setHours(0, 0, 0, 0);
      const bars = await getRawBars(symbol, {
        timeframe: "1Min",
        start: todayStart.toISOString(),
        end: now.toISOString(),
      });
      return bars.map(mapBar);
    })(),
  ]);

  if (cached && cached.date === today) {
    return {
      intraday: rawIntraday,
      daily: cached.daily,
      avgBaselineVolume: cached.avgBaselineVolume,
    };
  }

  // Cache miss / stale — refetch daily history and baseline volume
  const full = await fetchBarsForSymbol(symbol, opts);
  dailyCache.set(symbol, {
    date: today,
    daily: full.daily,
    avgBaselineVolume: full.avgBaselineVolume,
  });
  return full;
}

export { fetchBarsForSymbol, fetchBarsForSymbolCached, getRawBars };
