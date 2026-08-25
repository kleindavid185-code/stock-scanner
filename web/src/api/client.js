import { API_BASE_URL } from "./config";

let authToken = null;

export function setAuthToken(token) {
  authToken = token;
}

async function request(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...options.headers };
  if (authToken) headers.Authorization = `Bearer ${authToken}`;

  const res = await fetch(`${API_BASE_URL}${path}`, { ...options, headers });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    let message = body;
    try {
      message = JSON.parse(body).error || body;
    } catch {
      // not JSON, use raw text
    }
    throw new Error(message || `Request failed (${res.status})`);
  }
  return res.json();
}

export const api = {
  signup: (email, password) =>
    request("/api/auth/signup", { method: "POST", body: JSON.stringify({ email, password }) }),
  login: (email, password) =>
    request("/api/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  me: () => request("/api/auth/me"),

  scan: () => request("/api/scan"),
  aiSearch: (query) =>
    request("/api/ai-search", {
      method: "POST",
      body: JSON.stringify({ query }),
    }),
  quote: (symbol) => request(`/api/quote/${symbol}`),
  getWatchlists: () => request("/api/watchlists"),
  createWatchlist: (name) =>
    request(`/api/watchlists/${encodeURIComponent(name)}`, { method: "POST" }),
  deleteWatchlist: (name) =>
    request(`/api/watchlists/${encodeURIComponent(name)}`, {
      method: "DELETE",
    }),
  addSymbol: (name, symbol) =>
    request(`/api/watchlists/${encodeURIComponent(name)}/symbols`, {
      method: "POST",
      body: JSON.stringify({ symbol }),
    }),
  removeSymbol: (name, symbol) =>
    request(
      `/api/watchlists/${encodeURIComponent(name)}/symbols/${symbol}`,
      { method: "DELETE" }
    ),
  watchlistQuotes: (name) =>
    request(`/api/watchlists/${encodeURIComponent(name)}/quotes`),
  getSignals: () => request("/api/signals"),
  getSignal: (symbol) => request(`/api/signals/${symbol}`),
  getInsight: (symbol) => request(`/api/insight/${symbol}`),
  getTechEarnings: () => request("/api/earnings/tech"),

  adminListUsers: () => request("/api/admin/users"),
  adminSetUserRole: (userId, role) =>
    request(`/api/admin/users/${userId}/role`, {
      method: "POST",
      body: JSON.stringify({ role }),
    }),
};
