import "dotenv/config";
import express from "express";
import cors from "cors";
import NodeCache from "node-cache";
import {
  getMostActive,
  getMovers,
  getSnapshots,
  getBars,
  getBarsForSymbols,
} from "./alpacaClient.js";
import { rankCandidates } from "./scoring.js";
import { aiSearchCandidates } from "./aiSearch.js";
import { getStockInsight } from "./newsInsight.js";
import { getTechEarnings } from "./earningsCalendar.js";
import * as watchlists from "./watchlistStore.js";
import {
  router as signalRouter,
  startSignalPolling,
} from "../signal-engine/signalRoute.js";

const app = express();
app.use(cors());
app.use(express.json());

// Cache scan results briefly -- free-tier Alpaca has rate limits, and a
// mobile app polling every few seconds would burn through them fast.
const cache = new NodeCache({ stdTTL: 15 });

// News insight isn't meant to auto-poll (news doesn't change every 15s,
// and each call costs an Anthropic request) -- this just protects against
// a user mashing the manual refresh button from re-fetching+re-synthesizing
// on every click.
const insightCache = new NodeCache({ stdTTL: 120 });

// Alpha Vantage's free tier has a very low daily call budget (historically
// ~25 requests/day) and an earnings calendar doesn't meaningfully change
// within a day -- cache for hours, not seconds.
const earningsCache = new NodeCache({ stdTTL: 6 * 60 * 60 });

async function runScan() {
  const cacheKey = "scan";
  const cached = cache.get(cacheKey);
  if (cached) return cached;

  const [actives, movers] = await Promise.all([
    getMostActive(100),
    getMovers(50),
  ]);

  const symbolSet = new Set();
  actives.forEach((a) => symbolSet.add(a.symbol));
  (movers.gainers || []).forEach((m) => symbolSet.add(m.symbol));
  (movers.losers || []).forEach((m) => symbolSet.add(m.symbol));

  const symbols = Array.from(symbolSet).slice(0, 150);
  const [snapshots, barsBySymbol] = await Promise.all([
    getSnapshots(symbols),
    // Historical daily bars for trend classification (uptrend/downtrend/
    // choppy), used to prioritize sorting. Best-effort -- if this batch
    // call fails, scan still works, candidates just rank without a trend
    // boost.
    getBarsForSymbols(symbols, { timeframe: "1Day", limit: 20 }).catch((err) => {
      console.error("[scan] failed to fetch bars for trend classification:", err.message);
      return {};
    }),
  ]);
  const ranked = rankCandidates(snapshots, barsBySymbol);

  const result = { generatedAt: new Date().toISOString(), candidates: ranked };
  cache.set(cacheKey, result);
  return result;
}

// GET /api/scan -> ranked list of currently-active/volatile stocks.
// This is the core "scan the market" endpoint.
app.get("/api/scan", async (req, res) => {
  try {
    const result = await runScan();
    res.json(result);
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: err.message });
  }
});

// POST /api/ai-search { query: string } -> AI-filtered subset of the
// current scan, each with a one-line reason it matches the request.
app.post("/api/ai-search", async (req, res) => {
  try {
    const { query } = req.body;
    if (!query || !query.trim()) {
      return res.status(400).json({ error: "query is required" });
    }
    const scan = await runScan();
    const matches = await aiSearchCandidates(query, scan.candidates);
    res.json({ query, matches });
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: err.message });
  }
});

// GET /api/quote/:symbol -> snapshot + recent daily bars for detail view.
app.get("/api/quote/:symbol", async (req, res) => {
  try {
    const symbol = req.params.symbol.toUpperCase();
    const [snapshots, bars] = await Promise.all([
      getSnapshots([symbol]),
      getBars(symbol, "1Day", 30),
    ]);
    res.json({ symbol, snapshot: snapshots[symbol] || null, bars });
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: err.message });
  }
});

// GET /api/insight/:symbol -> "why it's moving": Claude's synthesis of
// recent news for this symbol, plus the raw headlines it was based on.
// News-based context only -- no price targets, no predictions. Not polled
// on an interval; the frontend loads this once per page view and offers a
// manual refresh button instead.
app.get("/api/insight/:symbol", async (req, res) => {
  try {
    const symbol = req.params.symbol.toUpperCase();
    const cached = insightCache.get(symbol);
    if (cached) return res.json(cached);

    const insight = await getStockInsight(symbol);
    insightCache.set(symbol, insight);
    res.json(insight);
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: err.message });
  }
});

// GET /api/earnings/tech -> upcoming (3-month horizon) earnings for a
// broad tech-sector universe. Cached for hours since Alpha Vantage's free
// tier is call-limited and this data doesn't change intraday anyway.
app.get("/api/earnings/tech", async (req, res) => {
  try {
    const cacheKey = "earnings-tech";
    const cached = earningsCache.get(cacheKey);
    if (cached) return res.json(cached);

    const earnings = await getTechEarnings();
    const result = { generatedAt: new Date().toISOString(), earnings };
    earningsCache.set(cacheKey, result);
    res.json(result);
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: err.message });
  }
});

// Watchlists -- simple CRUD, single-user, stored in a local JSON file.
app.get("/api/watchlists", (req, res) => {
  res.json(watchlists.getAllWatchlists());
});

app.post("/api/watchlists/:name", (req, res) => {
  res.json(watchlists.createWatchlist(req.params.name));
});

app.delete("/api/watchlists/:name", (req, res) => {
  watchlists.deleteWatchlist(req.params.name);
  res.json({ ok: true });
});

app.post("/api/watchlists/:name/symbols", (req, res) => {
  const { symbol } = req.body;
  if (!symbol) return res.status(400).json({ error: "symbol required" });
  res.json(watchlists.addSymbol(req.params.name, symbol));
});

app.delete("/api/watchlists/:name/symbols/:symbol", (req, res) => {
  res.json(watchlists.removeSymbol(req.params.name, req.params.symbol));
});

// GET /api/watchlists/:name/quotes -> live snapshots for everything in a
// given watchlist, so the app can show current price/change for saved names.
app.get("/api/watchlists/:name/quotes", async (req, res) => {
  try {
    const symbols = watchlists.getWatchlist(req.params.name);
    if (!symbols.length) return res.json({});
    const snapshots = await getSnapshots(symbols);
    res.json(snapshots);
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: err.message });
  }
});

// Signals -- technical indicators + Claude-interpreted bullish/bearish/
// neutral read, polled in the background for every symbol across all
// saved watchlists.
app.use("/api/signals", signalRouter);

function currentWatchlistSymbols() {
  const all = watchlists.getAllWatchlists();
  return Array.from(new Set(Object.values(all).flat()));
}

const PORT = process.env.PORT || 4000;
app.listen(PORT, () => {
  console.log(`Stock scanner backend (read-only) running on port ${PORT}`);
  startSignalPolling(currentWatchlistSymbols, 60_000);
});
