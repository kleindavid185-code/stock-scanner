import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import FlashValue from "../components/FlashValue";
import { formatClock } from "../utils/format";

export default function WatchlistDetailPage() {
  const { name } = useParams();
  const navigate = useNavigate();
  const [symbols, setSymbols] = useState([]);
  const [quotes, setQuotes] = useState({});
  const [newSymbol, setNewSymbol] = useState("");
  const [lastUpdated, setLastUpdated] = useState(null);

  const load = useCallback(async () => {
    const lists = await api.getWatchlists();
    setSymbols(lists[name] || []);
    const q = await api.watchlistQuotes(name);
    setQuotes(q);
    setLastUpdated(new Date());
  }, [name]);

  useEffect(() => {
    load();
  }, [load]);

  const addSymbol = async () => {
    if (!newSymbol.trim()) return;
    await api.addSymbol(name, newSymbol.trim().toUpperCase());
    setNewSymbol("");
    load();
  };

  const removeSymbol = async (symbol) => {
    await api.removeSymbol(name, symbol);
    load();
  };

  return (
    <div className="page">
      <span className="back-link" onClick={() => navigate("/watchlists")}>
        ← Watchlists
      </span>
      <h2 style={{ marginTop: 0, marginBottom: lastUpdated ? 4 : 16 }}>
        {decodeURIComponent(name)}
      </h2>
      {lastUpdated && (
        <p className="timestamp">
          as of <span className="mono">{formatClock(lastUpdated)}</span>
        </p>
      )}

      <div className="form-row">
        <input
          className="text-input"
          placeholder="Add symbol (e.g. AAPL)"
          value={newSymbol}
          onChange={(e) => setNewSymbol(e.target.value.toUpperCase())}
          onKeyDown={(e) => e.key === "Enter" && addSymbol()}
        />
        <button className="btn" onClick={addSymbol}>
          Add
        </button>
      </div>

      <ul className="list">
        {symbols.map((symbol) => {
          const snap = quotes[symbol];
          const price = snap?.latestTrade?.p;
          const prevClose = snap?.prevDailyBar?.c;
          const changePct =
            price && prevClose
              ? (((price - prevClose) / prevClose) * 100).toFixed(2)
              : null;
          return (
            <li key={symbol} className="list-row">
              <div
                className="row-main"
                onClick={() => navigate(`/stock/${symbol}`)}
              >
                <div className="symbol">{symbol}</div>
              </div>
              <div className="row-right" style={{ display: "flex", alignItems: "center", gap: 14 }}>
                <div>
                  {price != null && (
                    <FlashValue as="div" value={price} className="price">
                      ${price.toFixed(2)}
                    </FlashValue>
                  )}
                  {changePct != null && (
                    <FlashValue
                      as="div"
                      value={Number(changePct)}
                      className="change"
                      style={{ color: changePct >= 0 ? "#3fb950" : "#f85149" }}
                    >
                      {changePct >= 0 ? "+" : ""}
                      {changePct}%
                    </FlashValue>
                  )}
                </div>
                <button
                  className="btn secondary"
                  onClick={(e) => {
                    e.stopPropagation();
                    removeSymbol(symbol);
                  }}
                >
                  Remove
                </button>
              </div>
            </li>
          );
        })}
      </ul>
      {!symbols.length && (
        <div className="empty">No symbols yet — add one above.</div>
      )}
    </div>
  );
}
