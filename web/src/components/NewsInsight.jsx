import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";

// "Why it's moving" -- loads once per symbol (no polling; news doesn't
// change every 15s like Signals data does) with a manual refresh button.
export default function NewsInsight({ symbol }) {
  const [insight, setInsight] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getInsight(symbol);
      setInsight(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [symbol]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="news-insight">
      <div className="section-title-row">
        <div className="section-title">Why it's moving</div>
        <button className="btn-refresh" onClick={load} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      {error && <p className="error-text">{error}</p>}

      {loading && !insight && <div className="center">Reading recent news…</div>}

      {insight && (
        <>
          <div className="insight-synthesis">
            <div className="insight-head">
              <span className={`signal-direction ${insight.synthesis.sentiment}`}>
                {insight.synthesis.sentiment}
              </span>
              {insight.synthesis.catalyst && (
                <span className="insight-catalyst">Catalyst: {insight.synthesis.catalyst}</span>
              )}
            </div>
            <p className="insight-summary">{insight.synthesis.summary}</p>
            <p className="insight-watch">Watch for: {insight.synthesis.watchFor}</p>
            <p className="disclaimer" style={{ marginTop: 10, marginBottom: 0 }}>
              News-based read, not a prediction — no price targets or "will go
              up/down" guarantees.
            </p>
          </div>

          <div className="insight-headlines">
            {insight.headlines.length ? (
              insight.headlines.map((h, i) => (
                <a
                  key={i}
                  className="insight-headline-row"
                  href={h.url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <div className="insight-headline-text">{h.headline}</div>
                  <div className="sub">
                    {h.source} · {new Date(h.createdAt).toLocaleString()}
                  </div>
                </a>
              ))
            ) : (
              <div className="empty">No recent headlines found for this symbol.</div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
