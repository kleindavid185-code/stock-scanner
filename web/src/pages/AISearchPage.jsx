import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";

const EXAMPLES = [
  "cheap stocks with huge volume today",
  "biggest gap ups this morning",
  "high volatility names under $5",
];

export default function AISearchPage() {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [matches, setMatches] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [searchedFor, setSearchedFor] = useState(null);

  const runSearch = async (q) => {
    const text = (q ?? query).trim();
    if (!text) return;
    setLoading(true);
    setError(null);
    try {
      const data = await api.aiSearch(text);
      setMatches(data.matches || []);
      setSearchedFor(text);
    } catch (e) {
      setError(e.message);
      setMatches(null);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="page">
      <p className="disclaimer">
        Describe what you're looking for. AI filters today's active-stock
        scan against your description — it can't see anything outside that
        list, and it's not predicting future moves.
      </p>

      <div className="form-row">
        <input
          className="text-input"
          placeholder="e.g. penny stocks with volume surging"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && runSearch()}
        />
        <button className="btn" onClick={() => runSearch()}>
          Go
        </button>
      </div>

      {!matches && !loading && (
        <div className="examples">
          <div className="examples-label">Try asking:</div>
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              className="example-chip"
              onClick={() => runSearch(ex)}
            >
              {ex}
            </button>
          ))}
        </div>
      )}

      {loading && <div className="center">Searching…</div>}
      {error && <p className="error-text">{error}</p>}

      {matches && !loading && (
        <>
          <p className="disclaimer">
            {matches.length
              ? `${matches.length} match${matches.length === 1 ? "" : "es"} for "${searchedFor}"`
              : `No matches for "${searchedFor}"`}
          </p>
          <ul className="list">
            {matches.map((item) => (
              <li
                key={item.symbol}
                className="list-row"
                style={{ flexDirection: "column", alignItems: "stretch" }}
                onClick={() => navigate(`/stock/${item.symbol}`)}
              >
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span className="symbol">{item.symbol}</span>
                  <span style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
                    <span className="price mono">${item.price.toFixed(2)}</span>
                    <span
                      className="change mono"
                      style={{ color: item.changePct >= 0 ? "#3fb950" : "#f85149" }}
                    >
                      {item.changePct >= 0 ? "+" : ""}
                      {item.changePct}%
                    </span>
                  </span>
                </div>
                <div className="sub" style={{ marginTop: 6 }}>{item.reason}</div>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
