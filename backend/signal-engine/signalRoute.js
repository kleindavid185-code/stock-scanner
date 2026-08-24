/**
 * signalRoute.js
 * Express route + polling loop that ties together:
 *   Alpaca bars -> indicators.js -> claudeSignal.js -> in-memory signal store
 *
 * Mount this in your existing backend, e.g.:
 *   const signalRouter = require("./signal-engine/signalRoute");
 *   app.use("/api/signals", signalRouter.router);
 *
 * You already have an Alpaca client in your scanner app backend — swap the
 * `fetchBarsForSymbol` stub below for your existing data-fetch function.
 */

import express from "express";
import { computeIndicatorBundle } from "./indicators.js";
import { getSignalsBatch } from "./claudeSignal.js";
import { fetchBarsForSymbolCached as fetchBarsForSymbol } from "./alpacaData.js";

const router = express.Router();

// In-memory store of the latest signal per symbol. Swap for a real DB
// (or your existing watchlist storage) if you want history/persistence.
const latestSignals = new Map();

/**
 * Runs one full pass: for every symbol in `watchlist`, pull bars, compute
 * indicators, batch through Claude, and update the in-memory store.
 */
async function runSignalPass(watchlist) {
  const pairs = [];

  for (const symbol of watchlist) {
    try {
      const { intraday, daily, avgBaselineVolume } = await fetchBarsForSymbol(symbol);
      const indicators = computeIndicatorBundle(daily, intraday, avgBaselineVolume);
      pairs.push({ symbol, indicators });
    } catch (err) {
      console.error(`[signal-engine] failed to build indicators for ${symbol}:`, err.message);
    }
  }

  if (!pairs.length) return;

  const signals = await getSignalsBatch(pairs);
  for (const signal of signals) {
    latestSignals.set(signal.symbol, {
      ...signal,
      updatedAt: new Date().toISOString(),
    });
  }
}

/**
 * Starts a polling loop. Call once at server startup, e.g.:
 *   startSignalPolling(() => currentWatchlist, 60_000);
 * `getWatchlist` is a function so you can point it at whatever watchlist
 * source you're already using (mutable array, DB query, etc).
 */
function startSignalPolling(getWatchlist, intervalMs = 60_000) {
  const tick = async () => {
    const watchlist = getWatchlist();
    if (watchlist && watchlist.length) {
      await runSignalPass(watchlist);
    }
  };
  tick(); // run immediately on startup
  return setInterval(tick, intervalMs);
}

// GET /api/signals — all latest signals
router.get("/", (req, res) => {
  res.json(Array.from(latestSignals.values()));
});

// GET /api/signals/:symbol — latest signal for one symbol
router.get("/:symbol", (req, res) => {
  const symbol = req.params.symbol.toUpperCase();
  const signal = latestSignals.get(symbol);
  if (!signal) return res.status(404).json({ error: "no signal yet for this symbol" });
  res.json(signal);
});

export { router, runSignalPass, startSignalPolling, fetchBarsForSymbol };
