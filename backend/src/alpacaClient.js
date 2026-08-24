// Read-only wrapper around Alpaca's Market Data API.
//
// IMPORTANT: This file only ever calls data.alpaca.markets (market data)
// endpoints, never api.alpaca.markets/v2/orders or anything under
// /account, /positions, etc. There is no trading capability anywhere
// in this codebase by design -- the app is view/analyze only.

const DATA_BASE_URL = "https://data.alpaca.markets";

function authHeaders() {
  const key = process.env.ALPACA_API_KEY;
  const secret = process.env.ALPACA_API_SECRET;
  if (!key || !secret) {
    throw new Error(
      "Missing ALPACA_API_KEY / ALPACA_API_SECRET. Copy .env.example to .env and fill in your keys."
    );
  }
  return {
    "APCA-API-KEY-ID": key,
    "APCA-API-SECRET-KEY": secret,
  };
}

async function alpacaGet(path, params = {}) {
  const url = new URL(DATA_BASE_URL + path);
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null) url.searchParams.set(k, v);
  }
  const res = await fetch(url, { headers: authHeaders() });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`Alpaca API error ${res.status}: ${body}`);
  }
  return res.json();
}

// Most-active-by-volume snapshot list. Alpaca exposes a "most actives"
// screener endpoint that's a good seed list for scanning without having
// to pull the full ~11k symbol universe on every request.
export async function getMostActive(top = 100) {
  const data = await alpacaGet("/v1beta1/screener/stocks/most-actives", {
    top,
  });
  return data.most_actives || [];
}

// Top gainers / losers screener -- useful for catching momentum names.
export async function getMovers(top = 50) {
  const data = await alpacaGet("/v1beta1/screener/stocks/movers", { top });
  return data; // { gainers: [...], losers: [...] }
}

// Latest snapshot (quote + latest trade + daily bar + prev daily bar) for
// a batch of symbols. This is the core data point scoring is built from.
export async function getSnapshots(symbols) {
  if (!symbols.length) return {};
  const feed = process.env.ALPACA_DATA_FEED || "iex";
  const data = await alpacaGet("/v2/stocks/snapshots", {
    symbols: symbols.join(","),
    feed,
  });
  return data.snapshots || data; // { SYM: { latestTrade, dailyBar, prevDailyBar, ... } }
}

// Recent minute/day bars for a single symbol, used for the detail/chart view.
export async function getBars(symbol, timeframe = "1Day", limit = 30) {
  const feed = process.env.ALPACA_DATA_FEED || "iex";
  const data = await alpacaGet(`/v2/stocks/${symbol}/bars`, {
    timeframe,
    limit,
    feed,
  });
  return data.bars || [];
}
