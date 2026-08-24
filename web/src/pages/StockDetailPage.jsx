import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import TradingViewChart from "../components/TradingViewChart";

function Stat({ label, value }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value mono">{value ?? "—"}</div>
    </div>
  );
}

export default function StockDetailPage() {
  const { symbol } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api
      .quote(symbol)
      .then(setData)
      .finally(() => setLoading(false));
  }, [symbol]);

  if (loading) return <div className="center">Loading…</div>;

  const snap = data?.snapshot;
  const price = snap?.latestTrade?.p;
  const prevClose = snap?.prevDailyBar?.c;
  const changePct =
    price && prevClose ? (((price - prevClose) / prevClose) * 100).toFixed(2) : null;

  return (
    <div className="page">
      <span className="back-link" onClick={() => navigate(-1)}>
        ← Back
      </span>
      <h1 style={{ margin: "0 0 4px", fontSize: 26 }}>{symbol}</h1>

      {price != null && (
        <div style={{ display: "flex", gap: 10, alignItems: "baseline" }}>
          <span className="price mono" style={{ fontSize: 20 }}>${price.toFixed(2)}</span>
          {changePct != null && (
            <span
              className="change mono"
              style={{ fontSize: 15, color: changePct >= 0 ? "#3fb950" : "#f85149" }}
            >
              {changePct >= 0 ? "+" : ""}
              {changePct}%
            </span>
          )}
        </div>
      )}

      <TradingViewChart symbol={symbol} />

      {snap?.dailyBar && (
        <div className="stats-grid">
          <Stat label="Open" value={snap.dailyBar.o?.toFixed(2)} />
          <Stat label="High" value={snap.dailyBar.h?.toFixed(2)} />
          <Stat label="Low" value={snap.dailyBar.l?.toFixed(2)} />
          <Stat label="Volume" value={snap.dailyBar.v?.toLocaleString()} />
        </div>
      )}

      <div className="section-title">Recent daily bars</div>
      {(data?.bars || [])
        .slice()
        .reverse()
        .map((bar, i) => (
          <div key={i} className="bar-row">
            <span className="bar-date mono">{bar.t?.slice(0, 10)}</span>
            <span className="mono">
              O {bar.o?.toFixed(2)} H {bar.h?.toFixed(2)} L {bar.l?.toFixed(2)} C{" "}
              {bar.c?.toFixed(2)}
            </span>
          </div>
        ))}
    </div>
  );
}
