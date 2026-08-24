import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import FlashValue from "../components/FlashValue";
import { formatClock } from "../utils/format";

export default function ScannerPage() {
  const navigate = useNavigate();
  const [candidates, setCandidates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      const data = await api.scan();
      setCandidates(data.candidates || []);
      setLastUpdated(new Date());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 15000);
    return () => clearInterval(id);
  }, [load]);

  if (loading) return <div className="center">Loading…</div>;

  return (
    <div className="page">
      <p className="disclaimer">
        Ranked by volume surge, momentum & range — trending names (clear
        uptrend/downtrend) sorted above choppy ones. Hard cutoffs: $5+
        price, obviously broken data (e.g. -90%+ crashes), and broad
        ETFs/mega-caps (SPY, AAPL, and similar) excluded entirely —
        everything else (RVOL, momentum, trend) just affects rank and
        flags, not inclusion. A screener, not a prediction — use your own
        judgment.
      </p>
      {lastUpdated && (
        <p className="timestamp">
          as of <span className="mono">{formatClock(lastUpdated)}</span>
        </p>
      )}
      {error && <p className="error-text">{error}</p>}
      <ul className="list list--dense">
        {candidates.map((item, index) => (
          <li
            key={item.symbol}
            className="list-row"
            onClick={() => navigate(`/stock/${item.symbol}`)}
          >
            <span className="rank mono">{index + 1}</span>
            <div className="row-main">
              <div className="symbol">{item.symbol}</div>
              <div className="sub">
                RVOL <span className="mono">{item.rvol}x</span>
                {item.lowConfidence && (
                  <span className="data-flag" title="Extremely high RVOL — often thin/illiquid data, not a genuine surge">
                    ⚠ thin data
                  </span>
                )}{" "}
                · Range <span className="mono">{item.rangePct}%</span>
              </div>
            </div>
            <div className="row-right">
              <FlashValue as="div" value={item.price} className="price">
                ${item.price.toFixed(2)}
              </FlashValue>
              <FlashValue
                as="div"
                value={item.changePct}
                className="change"
                style={{ color: item.changePct >= 0 ? "#3fb950" : "#f85149" }}
              >
                {item.changePct >= 0 ? "+" : ""}
                {item.changePct}%
              </FlashValue>
            </div>
          </li>
        ))}
        {!candidates.length && <div className="empty">No candidates right now.</div>}
      </ul>
    </div>
  );
}
