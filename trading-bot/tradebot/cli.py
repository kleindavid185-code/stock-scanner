"""Command-line interface. Run `tradebot --help` (or `python -m tradebot --help`)."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .config import load_config


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


def cmd_auth(cfg, a):
    from .broker.schwab_broker import make_schwab_client

    if cfg.schwab.token_path.exists() and not a.force:
        print(f"token exists at {cfg.schwab.token_path}; use --force to re-login")
        return
    if a.force and cfg.schwab.token_path.exists():
        cfg.schwab.token_path.unlink()
    make_schwab_client(cfg, interactive=True)
    cfg.schwab.token_path.chmod(0o600)
    print(f"Saved token to {cfg.schwab.token_path}. Re-run `tradebot auth --force` every 7 days.")


def cmd_accounts(cfg, a):
    from .broker.schwab_broker import SchwabBroker, make_schwab_client

    c = make_schwab_client(cfg)
    r = c.get_account_numbers()
    r.raise_for_status()
    for acct in r.json():
        num = acct["accountNumber"]
        print(f"account ...{num[-4:]}  hash={acct['hashValue']}")
    if len(r.json()) == 1 or cfg.schwab.account_hash:
        _print(SchwabBroker(c, cfg.schwab.account_hash).account_summary())


def cmd_fetch(cfg, a):
    from .data.base import load_bars

    bars = load_bars(cfg, a.symbols or cfg.symbols, start=a.start, refresh=a.refresh)
    print(f"{len(bars.symbols)} symbols, {len(bars.index)} days "
          f"({bars.index[0].date()} .. {bars.index[-1].date()})")


def _bars(cfg, a, symbols=None):
    from .data.base import load_bars
    from .data.synthetic import SyntheticProvider

    prov = SyntheticProvider(trend_edge=0.0015) if getattr(a, "synthetic", False) else None
    syms = symbols or a.symbols or cfg.symbols
    if cfg.benchmark not in syms:
        syms = syms + [cfg.benchmark]
    return load_bars(cfg, syms, start=getattr(a, "start", None), end=getattr(a, "end", None), provider=prov)


def cmd_backtest(cfg, a):
    from .backtest.metrics import compute_metrics, format_metrics
    from .research.discovery import evaluate

    bars = _bars(cfg, a)
    params = json.loads(a.params) if a.params else {}
    syms = [s for s in (a.symbols or cfg.symbols) if s in bars.symbols]
    r, m, res = evaluate(a.strategy, params, bars.select(syms), cfg)
    print(f"{a.strategy} {params or '(defaults)'} on {len(syms)} symbols")
    print(format_metrics(m))
    if cfg.benchmark in bars.symbols:
        b = bars.close[cfg.benchmark].pct_change().loc[r.index[0]:].fillna(0)
        bm = compute_metrics(b)
        print(f"\n  benchmark {cfg.benchmark}: CAGR {bm['cagr']:.2%}  Sharpe {bm['sharpe']:.2f}  "
              f"maxDD {bm['max_drawdown']:.2%}")
    if a.out:
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        res.equity.to_csv(out / "equity.csv")
        res.trades.to_csv(out / "trades.csv", index=False)
        print(f"\nwrote {out}/equity.csv and trades.csv")


def cmd_discover(cfg, a):
    import time

    from .research.discovery import discover
    from .store import Store

    while True:
        bars = _bars(cfg, a)
        s = discover(cfg, bars, Store(cfg.db_path), n_trials=a.trials, seed=a.seed)
        print(f"\nRun #{s['run_id']}: {s['trials']} trials this run, {s['total_trials_ever']} ever "
              f"(DSR pass threshold {s['dsr_threshold']:.3f})")
        if s.get("benchmark_sharpe") is not None:
            print(f"Benchmark {cfg.benchmark} Sharpe over research window: {s['benchmark_sharpe']:.2f}")
        for fam, v in s["families"].items():
            print(f"\n  {fam}: walk-forward OOS Sharpe {v['wf_sharpe']:.2f}")
            for x in v.get("shortlist", []):
                tag = "PASS" if x["status"] == "candidate" else "fail"
                print(f"    [{tag}] Sharpe {x['sharpe']:.2f} DD {x['max_dd']:.1%} DSR {x['dsr']:.3f} "
                      f"trades {x['trades']}  {'; '.join(x['reasons'])}")
        print(f"\nNew candidates: {[c['id'] for c in s['candidates']]}  promoted to paper: {s['promoted']}")
        if not a.loop:
            break
        print(f"sleeping {a.interval_hours}h ...")
        time.sleep(a.interval_hours * 3600)


def cmd_strategies(cfg, a):
    from .store import Store

    rows = Store(cfg.db_path).strategies(a.status.split(",") if a.status else None)
    if not rows:
        print("no strategies yet -- run `tradebot discover`")
    for s in rows:
        rm = s.get("research") or {}
        hm = s.get("holdout") or {}
        sh = s.get("shadow") or {}
        print(f"#{s['id']:<4} {s['status']:<9} {s['family']:<20} score {s['score'] or 0:5.2f}  "
              f"DSR {s['dsr'] or 0:.3f}  IS-Sharpe {rm.get('sharpe', 0):.2f}  "
              f"holdout {hm.get('sharpe', float('nan')):.2f}  "
              f"fwd {sh.get('days', 0)}d {sh.get('total_return', 0):+.1%}")
        if a.verbose:
            print(f"       params {s['params']}\n       {s.get('notes')}")


def cmd_set_status(cfg, a, status):
    from .store import Store

    st = Store(cfg.db_path)
    s = st.strategy(a.id)
    if not s:
        sys.exit(f"no strategy #{a.id}")
    if status == "live" and not (s.get("shadow") or {}).get("eligible_for_live") and not a.force:
        sys.exit(f"#{a.id} hasn't completed its paper-trading period ({(s.get('shadow') or {}).get('days', 0)} days); "
                 "use --force to override (not recommended)")
    st.set_status(a.id, status, notes=(s.get("notes") or "") + f" | manually set {status}")
    print(f"#{a.id} -> {status}")


def cmd_review(cfg, a):
    from .live.runner import completed_bars, review
    from .store import Store

    st = Store(cfg.db_path)
    syms = sorted({x for s in st.strategies(["paper", "live"]) for x in s["symbols"]})
    if not syms:
        print("no paper/live strategies")
        return
    bars = completed_bars(_bars(cfg, a, syms), cfg.section("bot")["timezone"])
    for m in review(cfg, st, bars) or ["no status changes"]:
        print(m)


def cmd_run(cfg, a):
    from .live.runner import rebalance

    bars = None
    if a.synthetic:
        from .store import Store

        st = Store(cfg.db_path)
        syms = sorted({x for s in st.strategies(["paper", "live"]) for x in s["symbols"]}) or cfg.symbols
        bars = _bars(cfg, a, syms)
    _print(rebalance(cfg, a.mode, dry_run=a.dry_run, force=a.force, bars=bars))


def cmd_daemon(cfg, a):
    from .live.runner import daemon

    daemon(cfg, a.mode)


def cmd_status(cfg, a):
    from .execution.risk import RiskManager
    from .store import Store

    st = Store(cfg.db_path)
    for mode in ("paper", "live"):
        hist = st.equity_history(mode)
        pos = st.positions(mode)
        if not hist and not pos:
            continue
        print(f"== {mode} ==")
        print(f"  cash ${st.cash(mode):,.2f}   last equity "
              f"{('$%s on %s' % (format(hist[-1]['equity'], ',.2f'), hist[-1]['date'])) if hist else 'n/a'}")
        if len(hist) > 1:
            print(f"  since start: {hist[-1]['equity'] / hist[0]['equity'] - 1:+.2%} over {len(hist)} runs")
        for s, p in pos.items():
            print(f"  {s:<6} {p['qty']:>8.0f} @ {p['avg_cost']:.2f}")
        k = RiskManager(cfg, st).killed(mode)
        if k:
            print(f"  KILLED: {k}")
    ok, why = cfg.live_allowed()
    print(f"live trading: {'ENABLED' if ok else 'disabled (' + why + ')'}")


def cmd_kill(cfg, a):
    from .execution.risk import RiskManager
    from .store import Store

    rm = RiskManager(cfg, Store(cfg.db_path))
    if a.reset:
        rm.reset_kill(a.mode)
        print(f"kill switch reset for {a.mode}")
    else:
        rm.trip_kill(a.mode, a.reason or "manual kill")
        print(f"{a.mode} trading halted. `tradebot kill --reset --mode {a.mode}` to resume.")


def cmd_demo(cfg, a):
    """End-to-end run on synthetic data in a throwaway state dir."""
    import tempfile

    from .live.runner import rebalance, review
    from .research.discovery import discover
    from .store import Store
    from .data.base import load_bars
    from .data.synthetic import SyntheticProvider

    d = tempfile.mkdtemp(prefix="tradebot-demo-")
    cfg = load_config(a.config, overrides={"bot": {"state_dir": d},
                                           "universe": {"symbols": ["AAA", "BBB", "CCC", "DDD", "EEE",
                                                                    "FFF", "GGG", "HHH", "SPY"]}})
    print(f"demo state: {d}\nSYNTHETIC DATA with a planted trend effect -- numbers mean nothing about real markets.\n")
    bars = load_bars(cfg, start="2008-01-01", end="2025-06-30", provider=SyntheticProvider(trend_edge=0.0015))
    st = Store(cfg.db_path)
    s = discover(cfg, bars, st, n_trials=a.trials, seed=1)
    print(f"discovery: {s['trials']} trials, candidates {[c['id'] for c in s['candidates']]}, "
          f"promoted to paper {s['promoted']}")
    for fam, v in s["families"].items():
        print(f"  {fam:<20} walk-forward Sharpe {v['wf_sharpe']:.2f}")
    sub = bars.slice(None, "2025-06-30")
    print("\npaper rebalance:")
    out = rebalance(cfg, "paper", bars=sub, today=sub.index[-1].date() + __import__("datetime").timedelta(days=3))
    _print({k: out.get(k) for k in ("equity", "targets", "orders", "notes", "equity_after")})
    print("\nreview:", review(cfg, st, sub) or "no changes")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tradebot", description=__doc__)
    p.add_argument("--config", default=None, help="path to config.toml (default ./config.toml)")
    p.add_argument("-v", "--verbose-log", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("auth", help="log in to Schwab (OAuth) and save token")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_auth)

    s = sub.add_parser("accounts", help="list Schwab account hashes and balances")
    s.set_defaults(fn=cmd_accounts)

    s = sub.add_parser("fetch", help="download/refresh daily history into the cache")
    s.add_argument("--source", choices=["schwab", "yahoo", "csv"], help="override [data] source")
    s.add_argument("--symbols", nargs="*")
    s.add_argument("--start")
    s.add_argument("--refresh", action="store_true")
    s.set_defaults(fn=cmd_fetch)

    def data_args(x):
        x.add_argument("--symbols", nargs="*")
        x.add_argument("--start")
        x.add_argument("--end")
        x.add_argument("--synthetic", action="store_true", help="use synthetic data (testing only)")
        x.add_argument("--source", choices=["schwab", "yahoo", "csv"],
                       help="override [data] source, e.g. --source yahoo for free history")

    s = sub.add_parser("backtest", help="backtest one strategy")
    s.add_argument("strategy")
    s.add_argument("--params", help='JSON, e.g. \'{"sma": 200}\'')
    s.add_argument("--out", help="directory for equity/trades CSV")
    data_args(s)
    s.set_defaults(fn=cmd_backtest)

    s = sub.add_parser("discover", help="search for new strategies")
    s.add_argument("--trials", type=int)
    s.add_argument("--seed", type=int)
    s.add_argument("--loop", action="store_true", help="keep searching forever")
    s.add_argument("--interval-hours", type=float, default=24)
    data_args(s)
    s.set_defaults(fn=cmd_discover)

    s = sub.add_parser("strategies", help="list the strategy registry")
    s.add_argument("--status", help="comma list: candidate,paper,live,retired,rejected")
    s.add_argument("--verbose", action="store_true")
    s.set_defaults(fn=cmd_strategies)

    for name, status, hlp in (("approve", "live", "promote a paper strategy to LIVE trading"),
                              ("retire", "retired", "stop trading a strategy"),
                              ("paper", "paper", "put a strategy (back) into paper trading")):
        s = sub.add_parser(name, help=hlp)
        s.add_argument("id", type=int)
        s.add_argument("--force", action="store_true")
        s.set_defaults(fn=lambda cfg, a, st=status: cmd_set_status(cfg, a, st))

    s = sub.add_parser("review", help="update forward-test stats; auto-retire failing strategies")
    data_args(s)
    s.set_defaults(fn=cmd_review)

    s = sub.add_parser("run", help="rebalance once now")
    s.add_argument("--mode", choices=["paper", "live"], default="paper")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--force", action="store_true", help="run even if already ran today")
    data_args(s)
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("daemon", help="run forever: daily rebalance, review, periodic discovery")
    s.add_argument("--mode", choices=["paper", "live"], default="paper")
    s.set_defaults(fn=cmd_daemon)

    s = sub.add_parser("status", help="positions, equity, kill-switch state")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("kill", help="halt trading immediately (or --reset)")
    s.add_argument("--mode", choices=["paper", "live"], default="live")
    s.add_argument("--reset", action="store_true")
    s.add_argument("--reason")
    s.set_defaults(fn=cmd_kill)

    s = sub.add_parser("demo", help="end-to-end demo on synthetic data (no keys needed)")
    s.add_argument("--trials", type=int, default=120)
    s.set_defaults(fn=cmd_demo)
    return p


def main(argv=None) -> None:
    a = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose_log else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    overrides = {"data": {"source": a.source}} if getattr(a, "source", None) else None
    cfg = load_config(a.config, overrides=overrides)
    a.fn(cfg, a)


if __name__ == "__main__":
    main()
