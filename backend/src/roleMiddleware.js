import { getUserById } from "./auth.js";

const FULL_ACCESS_ROLES = new Set(["owner", "paid"]);

/**
 * Gates the Claude-powered features (Signals, AI Search, news insight)
 * behind owner/paid role. Always re-reads the role from the DB (never
 * trusts the JWT payload) so an admin-page role change takes effect
 * immediately, not after the user's token expires. Blocks BEFORE the
 * route handler runs, so a free user's request never reaches the code
 * that would call Claude.
 */
export function requireFullAccess(req, res, next) {
  const user = getUserById(req.userId);
  if (!user || !FULL_ACCESS_ROLES.has(user.role)) {
    return res.status(403).json({
      error: "Upgrade required — this feature is available on the paid tier.",
      upgradeRequired: true,
    });
  }
  next();
}

export function requireOwner(req, res, next) {
  const user = getUserById(req.userId);
  if (!user || user.role !== "owner") {
    return res.status(403).json({ error: "Owner access required." });
  }
  next();
}
