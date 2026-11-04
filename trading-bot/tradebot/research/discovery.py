"""Continuous strategy discovery with guards against overfitting.

Pipeline for every run:
  1. Split history: RESEARCH (older) | HOLDOUT (most recent N years, untouched).
  2. Randomly sample parameter sets for each strategy family and backtest them on
     RESEARCH only. Every trial is logged forever -- the cumulative trial count is
     what the Deflated Sharpe Ratio penalises, so "search until something looks
     lucky" is accounted for.
  3. Per family, run walk-forward optimisation over the sampled trials: does the
     *process* of picking the best params generalise out of sample?
  4. Shortlist each family's best trials and require, all at once:
        enough trades, tolerable drawdown, Deflated Sharpe >= min_dsr,
        family walk-forward Sharpe >= min_wf_sharpe,
        robust neighbourhood (nearby params also work, not a lone spike).
  5. Survivors face the HOLDOUT once. Pass -> 'candidate'.
  6. The best candidates are promoted to 'paper' (forward test on live data)
     up to max_paper_strategies. Live trading requires a human `approve`.
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..backtest.engine import CostModel, run_backtest
from ..backtest.metrics import compute_metrics, sharpe
from ..data.base import Bars
from ..store import Store
from ..backtest.daytrade import run_daytrade_backtest
from ..strategies import STRATEGIES, SWING_STRATEGIES, build, is_intraday
from .stats import deflated_sharpe
from .walkforward import walk_forward

log = logging.getLogger(__name__)


@dataclass
class Trial:
    family: str
    params: dict
    key: str
    returns: pd.Series
    metrics: dict


def cost_model(cfg) -> CostModel:
    b = cfg.section("backtest")
    return CostModel(commission_bps=b["commission_bps"], slippage_bps=b["slippage_bps"])


def evaluate(family: str, params: dict, bars: Bars, cfg, start=None) -> tuple[pd.Series, dict, object]:
    strat = build(family, params)
    w = strat.target_weights(bars)
    b = cfg.section("backtest")
    if strat.intraday:
        res = run_daytrade_backtest(bars, w, cost_model(cfg), b["initial_capital"])
    else:
        res = run_backtest(bars, w, cost_model(cfg), b["initial_capital"], b["rebalance_band"], start=start)
    # Exclude the warm-up period from statistics.
    warm = bars.index[min(strat.warmup, len(bars.index) - 1)]
    r = res.returns.loc[warm:]
    m = compute_metrics(r, res.trades[pd.to_datetime(res.trades["exit"]) >= warm] if len(res.trades) else res.trades,
                        res.turnover.loc[warm:], res.weights.loc[warm:])
    return r, m, res


def _neighbors(trial: Trial, pool: list[Trial]) -> list[Trial]:
    out = []
    for t in pool:
        if t.key == trial.key or t.family != trial.family:
            continue
        diff = sum(1 for k in trial.params if t.params.get(k) != trial.params[k])
        if diff == 1:
            out.append(t)
    return out


def discover(cfg, bars: Bars, store: Store, n_trials: int | None = None, seed: int | None = None,
             families: list[str] | None = None) -> dict:
    d = cfg.section("discovery")
    n_trials = n_trials or int(d["trials_per_run"])
    families = families or list(SWING_STRATEGIES)
    rng = random.Random(seed)
    symbols = [s for s in bars.symbols]
    holdout_start = bars.index[-1] - pd.DateOffset(days=int(d["holdout_years"] * 365.25))
    research = bars.slice(None, holdout_start - pd.Timedelta(days=1))
    if len(research.index) < 252 * (d["wf_train_years"] + d["wf_test_years"]):
        raise ValueError("not enough history for research + walk-forward; extend data.history_start")

    run_id = store.start_run("discover")
    tested = store.tested_keys()
    per_family = max(1, n_trials // len(families))
    trials: list[Trial] = []
    for fam in families:
        cls = STRATEGIES[fam]
        budget = min(per_family, cls.space_size())
        seen: set[str] = set()
        attempts = 0
        while len(seen) < budget and attempts < budget * 20:
            attempts += 1
            params = cls.sample_params(rng)
            key = cls(**params).key(symbols)
            if key in seen:
                continue
            seen.add(key)
            try:
                r, m, _ = evaluate(fam, params, research, cfg)
            except Exception as exc:  # a broken param combo shouldn't stop discovery
                log.warning("trial %s %s failed: %s", fam, params, exc)
                continue
            trials.append(Trial(fam, params, key, r, m))
        log.info("%s: %d trials", fam, len([t for t in trials if t.family == fam]))
    # Log trials even if previously tested: every look at the data counts.
    store.add_trials(run_id, [(t.family, t.key, sharpe(t.returns) / np.sqrt(252)) for t in trials])
    n_total = store.trial_count()
    # Multiple-testing correction. Trials are clustered by family (Lopez de Prado's
    # recommendation): DSR is computed against the expected max Sharpe of the
    # family's own all-time trials, and the pass threshold is tightened for the
    # number of families searched (Sidak correction).
    n_families = max(1, len(store.trial_families()))
    alpha = 1 - d["min_dsr"]
    dsr_threshold = (1 - alpha) ** (1 / n_families)  # = 1 - Sidak-adjusted alpha

    bench = cfg.benchmark
    bench_sharpe = bench_cagr = bench_holdout = None
    if bench in research.symbols:
        br = research.close[bench].pct_change().dropna()
        bench_sharpe = sharpe(br)
        bench_cagr = compute_metrics(br)["cagr"]
        bh = bars.close[bench].loc[holdout_start:].dropna()
        bench_holdout = float(bh.iloc[-1] / bh.iloc[0] - 1) if len(bh) > 1 else None

    summary = {"run_id": run_id, "trials": len(trials), "total_trials_ever": n_total, "families": {},
               "dsr_threshold": dsr_threshold,
               "candidates": [], "benchmark_sharpe": bench_sharpe, "benchmark_cagr": bench_cagr,
               "benchmark_holdout_return": bench_holdout, "previously_tested": len(tested)}
    for fam in families:
        pool = [t for t in trials if t.family == fam]
        if not pool:
            continue
        wf = walk_forward({t.key: t.returns for t in pool}, d["wf_train_years"], d["wf_test_years"])
        wf_sharpe = wf.metrics.get("sharpe", 0.0)
        summary["families"][fam] = {"trials": len(pool), "wf_sharpe": wf_sharpe,
                                    "wf_max_dd": wf.metrics.get("max_drawdown")}
        shortlist = sorted(pool, key=lambda t: t.metrics.get("sharpe", 0), reverse=True)[:3]
        for t in shortlist:
            m = t.metrics
            daily_sr = m.get("sharpe", 0) / np.sqrt(252)
            fam_sharpes = store.trial_sharpes(fam)
            dsr = deflated_sharpe(daily_sr, m["days"], m.get("skew", 0), m.get("kurtosis", 3),
                                  fam_sharpes, len(fam_sharpes))
            nb = _neighbors(t, pool)
            nb_sharpes = [x.metrics.get("sharpe", 0) for x in nb]
            robustness = float(np.median(nb_sharpes) / m["sharpe"]) if nb_sharpes and m.get("sharpe", 0) > 0 else 0.0
            reasons = []
            if m.get("trades", 0) < d["min_trades"]:
                reasons.append(f"trades {m.get('trades', 0)} < {d['min_trades']}")
            if m.get("max_drawdown", 1) > d["max_drawdown"]:
                reasons.append(f"maxDD {m['max_drawdown']:.1%} > {d['max_drawdown']:.0%}")
            if dsr < dsr_threshold:
                reasons.append(f"DSR {dsr:.3f} < {dsr_threshold:.3f}")
            if wf_sharpe < d["min_wf_sharpe"]:
                reasons.append(f"walk-forward Sharpe {wf_sharpe:.2f} < {d['min_wf_sharpe']}")
            if nb and robustness < 0.5:
                reasons.append(f"fragile params (neighbours keep {robustness:.0%} of Sharpe)")
            holdout_m = None
            if not reasons:
                hr, holdout_m, _ = evaluate(fam, t.params, bars, cfg)
                hr = hr.loc[holdout_start:]
                holdout_m = compute_metrics(hr)
                if holdout_m.get("sharpe", 0) < d["min_holdout_sharpe"]:
                    reasons.append(f"holdout Sharpe {holdout_m.get('sharpe', 0):.2f} < {d['min_holdout_sharpe']}")
            status = "candidate" if not reasons else "rejected"
            score = _score(m, wf_sharpe, holdout_m, dsr, robustness)
            summary["families"][fam].setdefault("shortlist", []).append({
                "params": t.params, "sharpe": m.get("sharpe"), "max_dd": m.get("max_drawdown"),
                "cagr": m.get("cagr"), "beats_hold_cagr": bench_cagr is not None and m.get("cagr", 0) > bench_cagr,
                "holdout_return": (holdout_m or {}).get("total_return"),
                "trades": m.get("trades"), "dsr": dsr, "robustness": robustness,
                "holdout_sharpe": (holdout_m or {}).get("sharpe"), "status": status, "reasons": reasons})
            existing = store.strategy_by_key(t.key)
            if existing and existing["status"] in ("paper", "live", "retired"):
                continue  # don't overwrite strategies that are already in/through forward testing
            if status == "rejected" and existing is None and dsr < 0.5:
                continue  # don't clutter the registry with clearly-noise results
            sid = store.upsert_strategy(t.key, fam, t.params, symbols, status, score=score, dsr=dsr,
                                        research=m, walkforward=wf.metrics, holdout=holdout_m,
                                        notes="; ".join(reasons) or "passed all gates")
            if existing and existing["status"] != status:
                store.set_status(sid, status)
            if status == "candidate":
                summary["candidates"].append({"id": sid, "family": fam, "params": t.params,
                                              "score": score, "dsr": dsr})
    summary["promoted"] = promote_candidates(cfg, store)
    store.finish_run(run_id, summary)
    store.set("last_discovery", pd.Timestamp.now().isoformat())
    return summary


def _score(m: dict, wf_sharpe: float, holdout: dict | None, dsr: float, robustness: float) -> float:
    """Rank by conservative, out-of-sample-weighted Sharpe."""
    hs = holdout.get("sharpe", 0.0) if holdout else 0.0
    return float(0.3 * m.get("sharpe", 0) + 0.3 * wf_sharpe + 0.4 * hs) * dsr * min(1.0, max(robustness, 0.0) + 0.5)


def promote_candidates(cfg, store: Store) -> list[int]:
    cap = int(cfg.section("discovery")["max_paper_strategies"])
    active = store.strategies(["paper", "live"])
    slots = cap - len([s for s in active if s["status"] == "paper"])
    promoted = []
    active_families = {s["family"] for s in active}
    # Prefer diversity: one new strategy per family before doubling up.
    # Day-trade strategies stay research-only until live day-trade execution exists.
    cands = [s for s in store.strategies(["candidate"]) if s["family"] in STRATEGIES and not is_intraday(s["family"])]
    cands = sorted(cands, key=lambda s: (s["family"] in active_families, -(s["score"] or 0)))
    for s in cands:
        if slots <= 0:
            break
        store.set_status(s["id"], "paper", notes=(s.get("notes") or "") + " | promoted to paper")
        active_families.add(s["family"])
        promoted.append(s["id"])
        slots -= 1
    return promoted
