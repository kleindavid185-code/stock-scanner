"""Walk-forward optimisation (WFO).

For each fold: choose the best parameter set on the TRAIN window only, then
record how that choice performed on the following TEST window. Stitching the
test windows gives an honest out-of-sample track record of the *whole process*
(including parameter selection), which is what you actually trade.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..backtest.metrics import compute_metrics, sharpe


@dataclass
class WalkForwardResult:
    oos_returns: pd.Series
    chosen: list[tuple[pd.Timestamp, str]]   # (test start, key of params picked)
    metrics: dict


def folds(index: pd.DatetimeIndex, train_years: float, test_years: float):
    start = index[0]
    end = index[-1]
    train = pd.DateOffset(days=int(train_years * 365.25))
    test = pd.DateOffset(days=int(test_years * 365.25))
    t0 = start + train
    while t0 < end:
        t1 = min(t0 + test, end + pd.Timedelta(days=1))
        yield (t0 - train, t0, t1)
        t0 = t1


def walk_forward(candidate_returns: dict[str, pd.Series], train_years: float = 4.0,
                 test_years: float = 1.0, min_train_days: int = 252) -> WalkForwardResult:
    """candidate_returns: key -> daily returns of one parameter set on the same calendar."""
    if not candidate_returns:
        raise ValueError("no candidates")
    frame = pd.DataFrame(candidate_returns).fillna(0.0)
    pieces, chosen = [], []
    for tr_s, te_s, te_e in folds(frame.index, train_years, test_years):
        train = frame.loc[tr_s: te_s - pd.Timedelta(days=1)]
        test = frame.loc[te_s: te_e - pd.Timedelta(days=1)]
        if len(train) < min_train_days or len(test) == 0:
            continue
        scores = {k: sharpe(train[k]) for k in frame.columns}
        best = max(scores, key=scores.get)
        pieces.append(test[best])
        chosen.append((te_s, best))
    oos = pd.concat(pieces) if pieces else pd.Series(dtype=float)
    return WalkForwardResult(oos, chosen, compute_metrics(oos) if len(oos) > 1 else {})
