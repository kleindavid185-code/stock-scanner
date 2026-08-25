// SQLite-backed, per-user watchlist storage. Replaces the old shared
// watchlists.json file -- every function now takes a userId so each
// person only ever reads/writes their own data.

import db from "./db.js";

const MAX_SYMBOLS_PER_USER = 10;

export class WatchlistLimitError extends Error {
  constructor(message) {
    super(message);
    this.name = "WatchlistLimitError";
  }
}

function nowIso() {
  return new Date().toISOString();
}

function getOrCreateWatchlistId(userId, name) {
  const existing = db
    .prepare("SELECT id FROM watchlists WHERE user_id = ? AND name = ?")
    .get(userId, name);
  if (existing) return existing.id;
  const info = db
    .prepare("INSERT INTO watchlists (user_id, name, created_at) VALUES (?, ?, ?)")
    .run(userId, name, nowIso());
  return info.lastInsertRowid;
}

export function getAllWatchlists(userId) {
  const lists = db.prepare("SELECT id, name FROM watchlists WHERE user_id = ?").all(userId);
  const symbolStmt = db.prepare(
    "SELECT symbol FROM watchlist_symbols WHERE watchlist_id = ? ORDER BY id"
  );
  const result = {};
  for (const list of lists) {
    result[list.name] = symbolStmt.all(list.id).map((r) => r.symbol);
  }
  return result;
}

export function getWatchlist(userId, name) {
  const row = db
    .prepare("SELECT id FROM watchlists WHERE user_id = ? AND name = ?")
    .get(userId, name);
  if (!row) return [];
  return db
    .prepare("SELECT symbol FROM watchlist_symbols WHERE watchlist_id = ? ORDER BY id")
    .all(row.id)
    .map((r) => r.symbol);
}

export function createWatchlist(userId, name) {
  getOrCreateWatchlistId(userId, name);
  return getWatchlist(userId, name);
}

export function deleteWatchlist(userId, name) {
  // ON DELETE CASCADE handles watchlist_symbols.
  db.prepare("DELETE FROM watchlists WHERE user_id = ? AND name = ?").run(userId, name);
}

/**
 * Adds a symbol to one of a user's watchlists. Enforces MAX_SYMBOLS_PER_USER
 * as a distinct-symbol cap across ALL of that user's watchlists combined --
 * adding a symbol the user already watches elsewhere never counts against
 * the cap, only a genuinely new distinct symbol does.
 */
export function addSymbol(userId, name, symbol) {
  symbol = symbol.toUpperCase();
  const watchlistId = getOrCreateWatchlistId(userId, name);

  const alreadyInThisList = db
    .prepare("SELECT 1 FROM watchlist_symbols WHERE watchlist_id = ? AND symbol = ?")
    .get(watchlistId, symbol);

  if (!alreadyInThisList) {
    const userSymbols = getUserSymbols(userId);
    const isNewDistinctSymbol = !userSymbols.includes(symbol);
    if (isNewDistinctSymbol && userSymbols.length >= MAX_SYMBOLS_PER_USER) {
      throw new WatchlistLimitError(
        `Watchlist limit reached (${MAX_SYMBOLS_PER_USER} symbols max).`
      );
    }
    db.prepare("INSERT INTO watchlist_symbols (watchlist_id, symbol) VALUES (?, ?)").run(
      watchlistId,
      symbol
    );
  }
  return getWatchlist(userId, name);
}

export function removeSymbol(userId, name, symbol) {
  const row = db
    .prepare("SELECT id FROM watchlists WHERE user_id = ? AND name = ?")
    .get(userId, name);
  if (!row) return [];
  db.prepare("DELETE FROM watchlist_symbols WHERE watchlist_id = ? AND symbol = ?").run(
    row.id,
    symbol.toUpperCase()
  );
  return getWatchlist(userId, name);
}

/** Distinct symbols across all of one user's watchlists. */
export function getUserSymbols(userId) {
  const rows = db
    .prepare(
      `SELECT DISTINCT ws.symbol
       FROM watchlist_symbols ws
       JOIN watchlists w ON w.id = ws.watchlist_id
       WHERE w.user_id = ?`
    )
    .all(userId);
  return rows.map((r) => r.symbol);
}

/**
 * Distinct symbols across every FULL-ACCESS (owner/paid) user's watchlists
 * -- feeds the signal-engine poll union. Deliberately excludes free users'
 * symbols here, not just at the /api/signals response layer: the signal
 * poll runs in the background on a timer, independent of any request, so
 * gating only the route wouldn't stop a free user's watchlist symbols from
 * still triggering real (paid) Claude calls every poll cycle.
 */
export function getAllSymbolsAcrossAllUsers() {
  const rows = db
    .prepare(
      `SELECT DISTINCT ws.symbol
       FROM watchlist_symbols ws
       JOIN watchlists w ON w.id = ws.watchlist_id
       JOIN users u ON u.id = w.user_id
       WHERE u.role IN ('owner', 'paid')`
    )
    .all();
  return rows.map((r) => r.symbol);
}
