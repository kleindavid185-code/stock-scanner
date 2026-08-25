// Per-user daily usage counters -- currently just AI Search, which costs a
// Claude call per query. Resets at UTC midnight (deterministic, no DST
// edge cases to worry about for a small trusted group).

import db from "./db.js";

const DAILY_AI_SEARCH_LIMIT = 25;

function todayUtc() {
  return new Date().toISOString().slice(0, 10); // YYYY-MM-DD
}

/**
 * Atomically checks + increments today's AI Search usage for a user.
 * Returns { allowed, count } -- count is the count AFTER incrementing when
 * allowed, or the current (already-at-limit) count when not.
 */
export function checkAndIncrementAiSearchUsage(userId) {
  const date = todayUtc();

  const row = db
    .prepare("SELECT count FROM ai_search_usage WHERE user_id = ? AND usage_date = ?")
    .get(userId, date);
  const current = row?.count ?? 0;

  if (current >= DAILY_AI_SEARCH_LIMIT) {
    return { allowed: false, count: current };
  }

  db.prepare(
    `INSERT INTO ai_search_usage (user_id, usage_date, count) VALUES (?, ?, 1)
     ON CONFLICT(user_id, usage_date) DO UPDATE SET count = count + 1`
  ).run(userId, date);

  return { allowed: true, count: current + 1 };
}

export { DAILY_AI_SEARCH_LIMIT };
