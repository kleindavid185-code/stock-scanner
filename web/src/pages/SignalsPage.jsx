import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import FlashValue from "../components/FlashValue";
import UpgradeRequired from "../components/UpgradeRequired";
import { useAuth } from "../context/AuthContext";
import { formatClock } from "../utils/format";

export default function SignalsPage() {
  const navigate = useNavigate();
  const { hasFullAccess } = useAuth();
  const [signals, setSignals] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      const data = await api.getSignals();
      setSignals(data || []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!hasFullAccess) {
      setLoading(false);
      return;
    }
    load();
    const id = setInterval(load, 20000);
    return () => clearInterval(id);
  }, [load, hasFullAccess]);

  if (!hasFullAccess) {
    return (
      <div className="page">
        <UpgradeRequired feature="Signals" />
      </div>
    );
  }

  if (loading) return <div className="center">Loading…</div>;

  return (
    <div className="page">
      <p className="disclaimer">
        Claude's technical read on your watchlist symbols, refreshed by the
        backend's polling loop. Signal generation only — not financial
        advice, no order placement.
      </p>
      {error && <p className="error-text">{error}</p>}

      {signals.map((s) => (
        <div
          key={s.symbol}
          className="signal-card"
          onClick={() => navigate(`/stock/${s.symbol}`)}
          style={{ cursor: "pointer" }}
        >
          <div className="signal-head">
            <span className="symbol">{s.symbol}</span>
            <span className={`signal-direction ${s.direction}`}>
              {s.direction}
            </span>
          </div>
          <div className="signal-confidence">
            Confidence:{" "}
            <FlashValue value={s.confidence}>{s.confidence}%</FlashValue>
          </div>
          <div className="signal-reasoning">{s.reasoning}</div>
          {s.key_level_watch && (
            <div className="signal-level">Watch: {s.key_level_watch}</div>
          )}
          {(s.expected_range_today || s.expected_range_tomorrow) && (
            <div className="signal-range">
              <div className="signal-range-label">
                Expected range (ATR-based, not a prediction)
              </div>
              {s.expected_range_today && (
                <div className="signal-range-row">
                  <span className="signal-range-when">Today</span>
                  <span className="mono">
                    ${s.expected_range_today.low.toFixed(2)} – $
                    {s.expected_range_today.high.toFixed(2)}
                  </span>
                </div>
              )}
              {s.expected_range_tomorrow && (
                <div className="signal-range-row">
                  <span className="signal-range-when">Tomorrow</span>
                  <span className="mono">
                    ${s.expected_range_tomorrow.low.toFixed(2)} – $
                    {s.expected_range_tomorrow.high.toFixed(2)}
                  </span>
                </div>
              )}
            </div>
          )}
          {s.updatedAt && (
            <div className="signal-updated">
              as of <span className="mono">{formatClock(s.updatedAt)}</span>
            </div>
          )}
        </div>
      ))}

      {!signals.length && (
        <div className="empty">
          No signals yet — the backend polls once a minute; add symbols to a
          watchlist and check back shortly.
        </div>
      )}
    </div>
  );
}
