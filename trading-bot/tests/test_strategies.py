import numpy as np
import pytest

from tradebot.strategies import STRATEGIES, build


@pytest.mark.parametrize("name", sorted(STRATEGIES))
def test_weights_are_valid(name, bars):
    w = build(name).target_weights(bars)
    assert not w.isna().any().any()
    assert (w >= -1e-12).all().all()
    assert (w.sum(axis=1) <= 1 + 1e-9).all()


@pytest.mark.parametrize("name", sorted(STRATEGIES))
def test_no_lookahead(name, bars):
    """Weights at date t must not change when future bars are removed."""
    rng = np.random.default_rng(0)
    for _ in range(3):
        params = STRATEGIES[name].sample_params(__import__("random").Random(int(rng.integers(1e9))))
        s = build(name, params)
        full = s.target_weights(bars)
        cut = int(rng.integers(400, len(bars.index) - 5))
        t = bars.index[cut]
        partial = s.target_weights(bars.slice(None, t))
        np.testing.assert_allclose(full.loc[t].to_numpy(), partial.loc[t].to_numpy(), atol=1e-10,
                                   err_msg=f"{s} uses future data at {t}")


def test_unknown_param_rejected():
    with pytest.raises(ValueError):
        build("trend_sma", {"nope": 1})
