import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { formatClock } from "../utils/format";

const COLUMNS = [
  { key: "symbol", label: "Symbol" },
  { key: "company", label: "Company" },
  { key: "reportDate", label: "Report Date" },
  { key: "fiscalQuarterEnd", label: "Fiscal Q End" },
  { key: "epsEstimate", label: "EPS Est." },
];

export default function EarningsPage() {
  const [earnings, setEarnings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState("reportDate");
  const [sortDir, setSortDir] = useState("asc");

  const load = useCallback(async () => {
    try {
      setError(null);
      const data = await api.getTechEarnings();
      setEarnings(data.earnings || []);
      setLastUpdated(new Date());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const toggleSort = (key) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  };

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = q
      ? earnings.filter(
          (r) =>
            r.symbol.toLowerCase().includes(q) ||
            (r.company || "").toLowerCase().includes(q)
        )
      : earnings;

    return [...filtered].sort((a, b) => {
      let av = a[sortKey];
      let bv = b[sortKey];
      if (av == null) av = sortDir === "asc" ? Infinity : -Infinity;
      if (bv == null) bv = sortDir === "asc" ? Infinity : -Infinity;
      if (typeof av === "string") av = av.toLowerCase();
      if (typeof bv === "string") bv = bv.toLowerCase();
      if (av < bv) return sortDir === "asc" ? -1 : 1;
      if (av > bv) return sortDir === "asc" ? 1 : -1;
      return 0;
    });
  }, [earnings, query, sortKey, sortDir]);

  if (loading) return <div className="center">Loading…</div>;

  return (
    <div className="page">
      <p className="disclaimer">
        Upcoming earnings (next 3 months) across a broad tech-sector universe
        — semiconductors, software, internet/platform, hardware,
        cloud/enterprise, and tech-adjacent communication services. Via
        Alpha Vantage, cached for hours (their free tier is call-limited).
      </p>
      {lastUpdated && (
        <p className="timestamp">
          as of <span className="mono">{formatClock(lastUpdated)}</span>
        </p>
      )}
      {error && <p className="error-text">{error}</p>}

      <div className="form-row">
        <input
          className="text-input"
          placeholder="Filter by symbol or company name…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>

      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              {COLUMNS.map((col) => (
                <th key={col.key} onClick={() => toggleSort(col.key)}>
                  {col.label}
                  {sortKey === col.key ? (sortDir === "asc" ? " ▲" : " ▼") : ""}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.symbol}>
                <td className="mono">{row.symbol}</td>
                <td>{row.company}</td>
                <td className="mono">{row.reportDate}</td>
                <td className="mono">{row.fiscalQuarterEnd}</td>
                <td className="mono">
                  {row.epsEstimate != null ? row.epsEstimate.toFixed(2) : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!rows.length && <div className="empty">No matching upcoming earnings.</div>}
      </div>
    </div>
  );
}
