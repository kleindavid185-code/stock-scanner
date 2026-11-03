"""SQLite persistence: strategy registry, trial log, bot book, orders, equity, flags."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS strategies (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  key TEXT UNIQUE NOT NULL,
  family TEXT NOT NULL,
  params TEXT NOT NULL,
  symbols TEXT NOT NULL,
  status TEXT NOT NULL,            -- rejected | candidate | paper | live | retired
  created_at TEXT NOT NULL,
  status_changed_at TEXT NOT NULL,
  paper_since TEXT,
  live_since TEXT,
  score REAL,
  dsr REAL,
  research TEXT,                   -- metrics json
  walkforward TEXT,
  holdout TEXT,
  shadow TEXT,                     -- live/paper tracking metrics
  notes TEXT
);
CREATE TABLE IF NOT EXISTS trials (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER, family TEXT, key TEXT, sharpe_daily REAL, created_at TEXT
);
CREATE INDEX IF NOT EXISTS trials_key ON trials(key);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT, mode TEXT, started_at TEXT, finished_at TEXT, summary TEXT
);
CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER, mode TEXT, symbol TEXT, side TEXT, qty REAL, order_type TEXT,
  limit_price REAL, broker_order_id TEXT, status TEXT, filled_qty REAL, avg_price REAL,
  created_at TEXT, updated_at TEXT, error TEXT
);
CREATE TABLE IF NOT EXISTS ledger (
  mode TEXT, symbol TEXT, qty REAL, avg_cost REAL, PRIMARY KEY (mode, symbol)
);
CREATE TABLE IF NOT EXISTS equity (
  mode TEXT, date TEXT, equity REAL, cash REAL, PRIMARY KEY (mode, date)
);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    # ---- kv -------------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        row = self.db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def set(self, key: str, value: Any) -> None:
        self.db.execute("INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, json.dumps(value, default=str)))
        self.db.commit()

    # ---- runs -----------------------------------------------------------
    def start_run(self, kind: str, mode: str = "") -> int:
        cur = self.db.execute("INSERT INTO runs(kind,mode,started_at) VALUES(?,?,?)", (kind, mode, now()))
        self.db.commit()
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, summary: dict) -> None:
        self.db.execute("UPDATE runs SET finished_at=?, summary=? WHERE id=?",
                        (now(), json.dumps(summary, default=str), run_id))
        self.db.commit()

    # ---- trials (global multiple-testing counter) ------------------------
    def add_trials(self, run_id: int, rows: list[tuple[str, str, float]]) -> None:
        ts = now()
        self.db.executemany("INSERT INTO trials(run_id,family,key,sharpe_daily,created_at) VALUES(?,?,?,?,?)",
                            [(run_id, f, k, s, ts) for f, k, s in rows])
        self.db.commit()

    def trial_count(self) -> int:
        return int(self.db.execute("SELECT COUNT(*) FROM trials").fetchone()[0])

    def trial_sharpes(self, family: str | None = None) -> list[float]:
        q = "SELECT sharpe_daily FROM trials WHERE sharpe_daily IS NOT NULL"
        args: tuple = ()
        if family:
            q += " AND family=?"
            args = (family,)
        return [r[0] for r in self.db.execute(q, args)]

    def trial_families(self) -> list[str]:
        return [r[0] for r in self.db.execute("SELECT DISTINCT family FROM trials")]

    def tested_keys(self) -> set[str]:
        return {r[0] for r in self.db.execute("SELECT DISTINCT key FROM trials")}

    # ---- strategies -----------------------------------------------------
    def upsert_strategy(self, key: str, family: str, params: dict, symbols: list[str], status: str,
                        score: float | None = None, dsr: float | None = None, research: dict | None = None,
                        walkforward: dict | None = None, holdout: dict | None = None,
                        notes: str = "") -> int:
        ts = now()
        existing = self.strategy_by_key(key)
        if existing:
            self.db.execute(
                "UPDATE strategies SET score=?, dsr=?, research=?, walkforward=?, holdout=?, notes=? WHERE key=?",
                (score, dsr, _j(research), _j(walkforward), _j(holdout), notes, key))
            self.db.commit()
            return existing["id"]
        cur = self.db.execute(
            "INSERT INTO strategies(key,family,params,symbols,status,created_at,status_changed_at,score,dsr,"
            "research,walkforward,holdout,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (key, family, json.dumps(params, default=str), json.dumps(symbols), status, ts, ts, score, dsr,
             _j(research), _j(walkforward), _j(holdout), notes))
        self.db.commit()
        return int(cur.lastrowid)

    def set_status(self, sid: int, status: str, notes: str | None = None) -> None:
        ts = now()
        extra = ""
        if status == "paper":
            extra = ", paper_since=COALESCE(paper_since, ?)"
        elif status == "live":
            extra = ", live_since=?"
        sql = f"UPDATE strategies SET status=?, status_changed_at=?{extra}" + (", notes=?" if notes else "") + " WHERE id=?"
        args: list[Any] = [status, ts]
        if extra:
            args.append(ts)
        if notes:
            args.append(notes)
        args.append(sid)
        self.db.execute(sql, args)
        self.db.commit()

    def set_shadow(self, sid: int, shadow: dict) -> None:
        self.db.execute("UPDATE strategies SET shadow=? WHERE id=?", (_j(shadow), sid))
        self.db.commit()

    def strategy(self, sid: int) -> dict | None:
        row = self.db.execute("SELECT * FROM strategies WHERE id=?", (sid,)).fetchone()
        return _row(row)

    def strategy_by_key(self, key: str) -> dict | None:
        row = self.db.execute("SELECT * FROM strategies WHERE key=?", (key,)).fetchone()
        return _row(row)

    def strategies(self, statuses: list[str] | None = None) -> list[dict]:
        if statuses:
            q = f"SELECT * FROM strategies WHERE status IN ({','.join('?' * len(statuses))}) ORDER BY score DESC"
            rows = self.db.execute(q, statuses).fetchall()
        else:
            rows = self.db.execute("SELECT * FROM strategies ORDER BY id").fetchall()
        return [_row(r) for r in rows]

    # ---- ledger / book --------------------------------------------------
    def positions(self, mode: str) -> dict[str, dict]:
        rows = self.db.execute("SELECT symbol, qty, avg_cost FROM ledger WHERE mode=? AND qty != 0", (mode,))
        return {r["symbol"]: {"qty": r["qty"], "avg_cost": r["avg_cost"]} for r in rows}

    def apply_fill(self, mode: str, symbol: str, qty: float, price: float) -> None:
        """qty > 0 buy, < 0 sell. Updates position and the bot's cash book."""
        pos = self.positions(mode).get(symbol, {"qty": 0.0, "avg_cost": 0.0})
        new_qty = pos["qty"] + qty
        avg = pos["avg_cost"]
        if qty > 0:
            avg = (pos["qty"] * pos["avg_cost"] + qty * price) / new_qty
        if abs(new_qty) < 1e-9:
            new_qty, avg = 0.0, 0.0
        self.db.execute("INSERT INTO ledger(mode,symbol,qty,avg_cost) VALUES(?,?,?,?) "
                        "ON CONFLICT(mode,symbol) DO UPDATE SET qty=excluded.qty, avg_cost=excluded.avg_cost",
                        (mode, symbol, new_qty, avg))
        self.db.commit()
        self.set(f"cash:{mode}", self.cash(mode) - qty * price)

    def set_position(self, mode: str, symbol: str, qty: float) -> None:
        self.db.execute("UPDATE ledger SET qty=? WHERE mode=? AND symbol=?", (qty, mode, symbol))
        self.db.commit()

    def cash(self, mode: str) -> float:
        return float(self.get(f"cash:{mode}", 0.0))

    def init_book(self, mode: str, cash: float) -> None:
        if self.get(f"cash:{mode}") is None:
            self.set(f"cash:{mode}", float(cash))

    # ---- orders & equity ------------------------------------------------
    def record_order(self, run_id: int, mode: str, o: dict) -> int:
        ts = now()
        cur = self.db.execute(
            "INSERT INTO orders(run_id,mode,symbol,side,qty,order_type,limit_price,broker_order_id,status,"
            "filled_qty,avg_price,created_at,updated_at,error) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, mode, o["symbol"], o["side"], o["qty"], o.get("order_type"), o.get("limit_price"),
             o.get("broker_order_id"), o.get("status"), o.get("filled_qty", 0), o.get("avg_price"), ts, ts,
             o.get("error")))
        self.db.commit()
        return int(cur.lastrowid)

    def recent_orders(self, mode: str, limit: int = 20) -> list[dict]:
        rows = self.db.execute("SELECT * FROM orders WHERE mode=? ORDER BY id DESC LIMIT ?", (mode, limit))
        return [dict(r) for r in rows]

    def record_equity(self, mode: str, date: str, equity: float, cash: float) -> None:
        self.db.execute("INSERT INTO equity(mode,date,equity,cash) VALUES(?,?,?,?) ON CONFLICT(mode,date) "
                        "DO UPDATE SET equity=excluded.equity, cash=excluded.cash", (mode, date, equity, cash))
        self.db.commit()

    def equity_history(self, mode: str) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM equity WHERE mode=? ORDER BY date", (mode,))]


def _j(x):
    return None if x is None else json.dumps(x, default=_json_default)


def _json_default(o):
    try:
        import numpy as np

        if isinstance(o, np.generic):
            return o.item()
    except ImportError:
        pass
    return str(o)


def _row(row) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    for k in ("params", "symbols", "research", "walkforward", "holdout", "shadow"):
        if d.get(k):
            d[k] = json.loads(d[k])
    return d
