"""Strategy, risk gate and backtester tests on hand-built price data.

These check the MECHANICS (does a breakout trigger, do stops fire, does the
gate block a good-faith violation...). They say nothing about whether the
strategy makes money -- only real historical data can answer that.
"""
import csv
import dataclasses
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from momentum_trader import eventlog  # noqa: E402
from momentum_trader.backtest import run_backtest, summarize, write_report  # noqa: E402
from momentum_trader.risk import (CashLedger, LimitOrder, OrderRejected, RiskGate,  # noqa: E402
                                  next_business_day, tick_round)
from momentum_trader.settings import load_settings  # noqa: E402
from momentum_trader.strategy import (Bar, ExitPlan, SymbolDayInfo, SymbolState,  # noqa: E402
                                      check_exit, relative_volume, update_and_check_entry)

S = load_settings()
INFO = SymbolDayInfo("TEST", prev_close=2.00, avg_daily_volume=1_000_000,
                     float_shares=8_000_000, short_pct_float=25.0)


def t(day, minute_index):
    m = 9 * 60 + 30 + minute_index
    return f"{day} {m // 60:02d}:{m % 60:02d}"


def quiet_bars(day, n, price=2.50, vol=50_000, start=0):
    return [Bar(t(day, start + i), price, price + 0.02, price - 0.02, price, vol) for i in range(n)]


class StrategyTests(unittest.TestCase):
    def run_bars(self, bars, info=INFO):
        st = SymbolState(info, S.entry.breakout_lookback_bars)
        return [sig for b in bars if (sig := update_and_check_entry(st, b, S.scanner, S.entry))]

    def test_breakout_with_volume_triggers(self):
        day = "2026-03-02"
        bars = quiet_bars(day, 10) + [Bar(t(day, 10), 2.50, 2.70, 2.50, 2.68, 200_000)]
        [sig] = self.run_bars(bars)
        self.assertEqual(sig.price, 2.68)
        self.assertAlmostEqual(sig.breakout_level, 2.52)
        self.assertGreaterEqual(sig.volume_ratio, S.entry.volume_confirm_multiple)

    def test_no_trigger_without_volume(self):
        day = "2026-03-02"
        bars = quiet_bars(day, 10) + [Bar(t(day, 10), 2.50, 2.70, 2.50, 2.68, 60_000)]
        self.assertEqual(self.run_bars(bars), [])

    def test_no_trigger_before_window(self):
        day = "2026-03-02"
        bars = quiet_bars(day, 2) + [Bar(t(day, 2), 2.50, 2.70, 2.50, 2.68, 900_000)]
        st = SymbolState(INFO, 2)
        self.assertEqual([s for b in bars if (s := update_and_check_entry(st, b, S.scanner, S.entry))], [])

    def test_no_trigger_if_not_up_enough(self):
        flat = dataclasses.replace(INFO, prev_close=2.45)   # only ~+9% on the day
        day = "2026-03-02"
        bars = quiet_bars(day, 10) + [Bar(t(day, 10), 2.50, 2.70, 2.50, 2.68, 200_000)]
        self.assertEqual(self.run_bars(bars, flat), [])

    def test_rvol_time_adjusted(self):
        # 100k shares by 09:39 on a 390k/day stock = 10x normal pace
        self.assertAlmostEqual(relative_volume(100_000, 390_000, "09:40"), 10.0)

    def test_exit_rules(self):
        ex = S.exit
        day = "2026-03-02"
        plan = ExitPlan.for_entry(2.00, ex)          # stop 1.90, target 2.20
        self.assertEqual(check_exit(plan, Bar(f"{day} 10:00", 2.0, 2.05, 1.89, 1.95, 1), "15:50"),
                         ("stop_loss", plan.stop_price))
        plan = ExitPlan.for_entry(2.00, ex)
        self.assertEqual(check_exit(plan, Bar(f"{day} 10:00", 2.0, 2.25, 1.99, 2.2, 1), "15:50"),
                         ("profit_target", plan.target_price))
        plan = ExitPlan.for_entry(2.00, ex)          # both touched -> stop assumed first
        self.assertEqual(check_exit(plan, Bar(f"{day} 10:00", 2.0, 2.30, 1.80, 2.0, 1), "15:50")[0],
                         "stop_loss")
        plan = ExitPlan.for_entry(2.00, ex)
        self.assertIsNone(check_exit(plan, Bar(f"{day} 10:00", 2.0, 2.15, 2.0, 2.14, 1), "15:50"))
        self.assertTrue(plan.trailing_armed)          # +7.5% > 3% activation
        reason, px = check_exit(plan, Bar(f"{day} 10:01", 2.12, 2.12, 2.05, 2.06, 1), "15:50")
        self.assertEqual(reason, "trailing_stop")
        self.assertAlmostEqual(px, 2.15 * 0.96)
        plan = ExitPlan.for_entry(2.00, ex)
        self.assertEqual(check_exit(plan, Bar(f"{day} 15:50", 2.1, 2.1, 2.1, 2.1, 1), "15:50"),
                         ("eod_flatten", 2.1))


class RiskTests(unittest.TestCase):
    def gate(self, **overrides):
        g = RiskGate(dataclasses.replace(S.risk, **overrides))
        g.start_day("2026-03-02")
        return g

    def test_limit_only_orders(self):
        self.assertEqual(LimitOrder("X", "BUY", 10, 2.5).order_type, "LIMIT")
        for bad in (dict(limit_price=0), dict(limit_price=float("nan")), dict(quantity=0),
                    dict(quantity=1.5), dict(side="SHORT")):
            args = dict(symbol="X", side="BUY", quantity=10, limit_price=2.5) | bad
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                LimitOrder(**args)

    def test_sizing_uses_smallest_limit(self):
        g = self.gate(max_position_dollars=500, max_account_pct_per_trade=10)
        # $1000 account -> 10% = $100 -> 40 shares at $2.50
        o = g.size_buy("X", 2.50, equity=1000, ledger=CashLedger(1000), open_positions=0)
        self.assertEqual((o.quantity, o.limit_price), (40, 2.50))
        # only $60 settled -> 24 shares
        o = g.size_buy("X", 2.50, equity=1000, ledger=CashLedger(60), open_positions=0)
        self.assertEqual(o.quantity, 24)

    def test_never_spends_unsettled_cash(self):
        led = CashLedger(100)
        led.receive_sale(900, "2026-03-06")            # Friday sale
        self.assertEqual(led.pending[0][0], "2026-03-09")  # settles Monday
        with self.assertRaisesRegex(OrderRejected, "good-faith"):
            led.pay_for_buy(500)
        led.settle_through("2026-03-09")
        led.pay_for_buy(500)
        self.assertAlmostEqual(led.settled, 500)

    def test_settlement_skips_holidays(self):
        self.assertEqual(next_business_day(date(2026, 11, 25)).isoformat(), "2026-11-27")

    def test_limits_block_orders(self):
        led = CashLedger(1000)
        g = self.gate(max_trades_per_day=1)
        g.record_entry()
        with self.assertRaisesRegex(OrderRejected, "max trades"):
            g.size_buy("X", 2, equity=1000, ledger=led, open_positions=0)
        g = self.gate(max_open_positions=1)
        with self.assertRaisesRegex(OrderRejected, "open positions"):
            g.size_buy("X", 2, equity=1000, ledger=led, open_positions=1)
        g = self.gate(max_daily_loss_dollars=50)
        g.record_realized(-50)
        self.assertTrue(g.day.halted)
        with self.assertRaisesRegex(OrderRejected, "halted"):
            g.size_buy("X", 2, equity=1000, ledger=led, open_positions=0)
        g.start_day("2026-03-03")                         # new day, fresh limits
        g.size_buy("X", 2, equity=1000, ledger=led, open_positions=0)

    def test_tick_rounding(self):
        self.assertEqual(tick_round(2.34567), 2.35)
        self.assertEqual(tick_round(0.123456), 0.1235)


class BacktestTests(unittest.TestCase):
    """End-to-end on a tiny synthetic dataset with known answers."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        eventlog.setup_logging(self.dir / "logs", console=False)
        self.universe = []

    def tearDown(self):
        self.tmp.cleanup()

    def add_day(self, day, bars, info=INFO):
        self.universe.append([day, info.symbol, info.prev_close, info.avg_daily_volume,
                              info.float_shares, info.short_pct_float])
        d = self.dir / "bars" / info.symbol
        d.mkdir(parents=True, exist_ok=True)
        with (d / f"{day}.csv").open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["time", "open", "high", "low", "close", "volume"])
            for b in bars:
                w.writerow([b.time, b.open, b.high, b.low, b.close, b.volume])

    def write_universe(self):
        with (self.dir / "universe.csv").open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["date", "symbol", "prev_close", "avg_daily_volume",
                        "float_shares", "short_pct_float"])
            w.writerows(self.universe)

    def winning_day(self, day):
        bars = quiet_bars(day, 10)
        bars.append(Bar(t(day, 10), 2.50, 2.70, 2.50, 2.68, 200_000))   # breakout signal
        bars.append(Bar(t(day, 11), 2.68, 2.69, 2.66, 2.68, 80_000))    # fill bar
        bars.append(Bar(t(day, 12), 2.70, 3.10, 2.69, 3.00, 90_000))    # hits +10% target (no new signal)
        bars += quiet_bars(day, 5, price=3.0, start=13)
        return bars

    def test_winning_trade_math(self):
        self.add_day("2026-03-02", self.winning_day("2026-03-02"))
        self.write_universe()
        r = run_backtest(S, self.dir)
        [tr] = r.trades
        # limit = 2.68 * 1.003 = 2.688 -> 2.69; fill = min(2.68*1.005, 2.69) = 2.69 (rounded)
        self.assertEqual(tr.entry_price, 2.69)
        self.assertEqual(tr.quantity, 37)             # $100 budget (10% of $1000)
        self.assertEqual(tr.exit_reason, "profit_target")
        target = 2.69 * 1.10
        self.assertAlmostEqual(tr.exit_price, tick_round(target * 0.995), places=4)
        self.assertAlmostEqual(tr.pnl, 37 * (tr.exit_price - 2.69), places=2)
        st = summarize(r)
        self.assertEqual(st["trades"], 1)
        self.assertEqual(st["win_rate_pct"], 100.0)
        self.assertAlmostEqual(st["net_profit"], tr.pnl, places=2)
        report = write_report(r, self.dir / "out")
        self.assertIn("Net profit", report.read_text())

    def test_no_overnight_and_settlement(self):
        day1, day2 = "2026-03-02", "2026-03-03"
        bars = self.winning_day(day1)[:12]            # data ends right after the fill
        self.add_day(day1, bars)
        self.add_day(day2, self.winning_day(day2))
        self.write_universe()
        r = run_backtest(S, self.dir)
        self.assertEqual([x.exit_reason for x in r.trades], ["eod_flatten", "profit_target"])
        self.assertEqual(r.trades[0].date, day1)      # closed same day, never held overnight

    def test_skips_large_float_and_unflagged_short_interest(self):
        big = dataclasses.replace(INFO, symbol="BIG", float_shares=50_000_000)
        low_si = dataclasses.replace(INFO, symbol="LOWSI", short_pct_float=2.0)
        self.add_day("2026-03-02", self.winning_day("2026-03-02"), big)
        self.add_day("2026-03-02", self.winning_day("2026-03-02"), low_si)
        self.write_universe()
        r = run_backtest(S, self.dir)
        self.assertEqual(r.trades, [])
        self.assertEqual(sum(r.skipped.values()), 2)


if __name__ == "__main__":
    unittest.main()
