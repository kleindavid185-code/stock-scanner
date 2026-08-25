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
import { WatchlistLimitError } from "./watchlistStore.js";
import { signup, login, getUserById, listUsers, setUserRole, AuthError } from "./auth.js";
import { requireAuth } from "./authMiddleware.js";
import { requireFullAccess, requireOwner } from "./roleMiddleware.js";
import { checkAndIncrementAiSearchUsage, DAILY_AI_SEARCH_LIMIT } from "./usageLimits.js";
import {
  router as signalRouter,
  startSignalPolling,
} from "../signal-engine/signalRoute.js";

const app = express();

// Allowed frontend origin(s) -- comma-separated if you need more than one
// (e.g. a custom domain plus the onrender.com URL). Defaults to the local
// Vite dev server so local dev keeps working with no config needed.
const allowedOrigins = (process.env.CORS_ORIGIN || "http://localhost:5173")
  .split(",")
  .map((o) => o.trim())
  .filter(Boolean);
app.use(cors({ origin: allowedOrigins }));

app.use(express.json());

// Auth -- signup/login are the only public routes. Everything else under
// /api requires a valid session token from here down.
app.post("/api/auth/signup", async (req, res) => {
  try {
    const { email, password } = req.body || {};
    const { user, token } = await signup(email, password);
    res.json({ user, token });
  } catch (err) {
    if (err instanceof AuthError) return res.status(400).json({ error: err.message });
    console.error(err);
    res.status(500).json({ error: err.message });
  }
});

app.post("/api/auth/login", async (req, res) => {
  try {
    const { email, password } = req.body || {};
    const { user, token } = await login(email, password);
    res.json({ user, token });
  } catch (err) {
    if (err instanceof AuthError) return res.status(401).json({ error: err.message });
    console.error(err);
    res.status(500).json({ error: err.message });
  }
});

app.use("/api", requireAuth);

// GET /api/auth/me -> lets the frontend validate a stored token on load
// without prompting for credentials again.
app.get("/api/auth/me", (req, res) => {
  const user = getUserById(req.userId);
  if (!user) return res.status(401).json({ error: "Not authenticated." });
  res.json({ user });
});

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

  const symbols = Array.from(symbolSet).slice(0, 200);
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
// owner/paid only -- requireFullAccess blocks free users before this
// handler (and therefore before any Claude call) ever runs. Capped
// per-user beyond that since each query still costs a Claude call.
app.post("/api/ai-search", requireFullAccess, async (req, res) => {
  try {
    const usage = checkAndIncrementAiSearchUsage(req.userId);
    if (!usage.allowed) {
      return res.status(429).json({
        error: `Daily AI Search limit reached (${DAILY_AI_SEARCH_LIMIT}/day) — resets at midnight UTC.`,
      });
    }

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
// manual refresh button instead. owner/paid only.
app.get("/api/insight/:symbol", requireFullAccess, async (req, res) => {
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

// Watchlists -- simple CRUD, per-user, stored in SQLite. Every route below
// scopes to req.userId (set by requireAuth) so users only ever see/manage
// their own lists.
app.get("/api/watchlists", (req, res) => {
  res.json(watchlists.getAllWatchlists(req.userId));
});

app.post("/api/watchlists/:name", (req, res) => {
  res.json(watchlists.createWatchlist(req.userId, req.params.name));
});

app.delete("/api/watchlists/:name", (req, res) => {
  watchlists.deleteWatchlist(req.userId, req.params.name);
  res.json({ ok: true });
});

app.post("/api/watchlists/:name/symbols", (req, res) => {
  const { symbol } = req.body || {};
  if (!symbol) return res.status(400).json({ error: "symbol required" });
  try {
    res.json(watchlists.addSymbol(req.userId, req.params.name, symbol));
  } catch (err) {
    if (err instanceof WatchlistLimitError) {
      return res.status(400).json({ error: err.message });
    }
    console.error(err);
    res.status(500).json({ error: err.message });
  }
});

app.delete("/api/watchlists/:name/symbols/:symbol", (req, res) => {
  res.json(watchlists.removeSymbol(req.userId, req.params.name, req.params.symbol));
});

// GET /api/watchlists/:name/quotes -> live snapshots for everything in a
// given watchlist, so the app can show current price/change for saved names.
app.get("/api/watchlists/:name/quotes", async (req, res) => {
  try {
    const symbols = watchlists.getWatchlist(req.userId, req.params.name);
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
// saved watchlists. owner/paid only for the response; the background poll
// itself already excludes free users' symbols entirely (see
// watchlistStore.getAllSymbolsAcrossAllUsers), so this is about giving a
// free user a clear message, not the only cost guard.
app.use("/api/signals", requireFullAccess, signalRouter);

// Admin -- owner only. Lets the app owner see every registered user and
// flip a user's role (e.g. to 'paid' once they've paid outside the app).
app.get("/api/admin/users", requireOwner, (req, res) => {
  res.json(listUsers());
});

app.post("/api/admin/users/:id/role", requireOwner, (req, res) => {
  const targetId = Number(req.params.id);
  if (targetId === Number(req.userId)) {
    return res.status(400).json({ error: "Can't change your own role here." });
  }
  try {
    const user = setUserRole(targetId, req.body?.role);
    res.json({ user });
  } catch (err) {
    if (err instanceof AuthError) return res.status(400).json({ error: err.message });
    console.error(err);
    res.status(500).json({ error: err.message });
  }
});

const PORT = process.env.PORT || 4000;
app.listen(PORT, () => {
  console.log(`Stock scanner backend (read-only) running on port ${PORT}`);
  // Union of every user's watchlist symbols -- one Claude call per unique
  // symbol per poll, not one per user per symbol.
  startSignalPolling(watchlists.getAllSymbolsAcrossAllUsers, 60_000);
});
