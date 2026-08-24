import { API_BASE_URL } from "./config";

async function request(path, options = {}) {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Request failed (${res.status}): ${text}`);
  }
  return res.json();
}

export const api = {
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
};
