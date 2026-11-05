"""Phase 1 tests: settings, .env storage, logging, Schwab auth wiring.

Run:  python -m unittest discover -s tests -v
No network and no real Schwab account needed; schwab-py is faked.
"""
import dataclasses
import json
import os
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from momentum_trader import envstore, eventlog, schwab_auth  # noqa: E402
from momentum_trader.paths import SETTINGS_FILE  # noqa: E402
from momentum_trader.settings import SettingsError, load_settings  # noqa: E402


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = SETTINGS_FILE.read_text()

    def tearDown(self):
        self.tmp.cleanup()

    def _load_with(self, old, new):
        assert old in self.base, old
        p = Path(self.tmp.name) / "settings.toml"
        p.write_text(self.base.replace(old, new, 1))
        return load_settings(p)

    def test_shipped_settings_are_valid_and_safe(self):
        s = load_settings()
        self.assertEqual(s.app.mode, "dryrun")
        self.assertFalse(s.app.auto_trading_enabled)
        self.assertFalse(s.auto_trading_active)
        self.assertNotIn(s.dashboard.port, (4000, 5173))

    def test_settings_are_read_only(self):
        s = load_settings()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            s.risk.max_daily_loss_dollars = 1_000_000

    def test_auto_needs_both_switches(self):
        s = self._load_with('mode = "dryrun"', 'mode = "auto"')
        self.assertFalse(s.auto_trading_active)

    def test_rejects_bad_values(self):
        cases = [
            ('mode = "dryrun"', 'mode = "yolo"'),
            ("max_daily_loss_dollars = 200.00", "max_daily_loss_dollars = -5"),
            ("max_account_pct_per_trade = 10.0", "max_account_pct_per_trade = 150"),
            ('flatten_at = "15:50"', 'flatten_at = "16:30"'),
            ('no_entries_after = "15:30"', 'no_entries_after = "15:55"'),
            ("port = 5055", "port = 4000"),
            ("max_price = 10.00", "max_price = 0.50"),
            ("max_trades_per_day = 5", 'max_trades_per_day = "five"'),
            ("max_open_positions = 2", "max_open_positions = 2\nmax_leverage = 4"),
        ]
        for old, new in cases:
            with self.subTest(new=new), self.assertRaises(SettingsError):
                self._load_with(old, new)

    def test_missing_setting_reported(self):
        with self.assertRaisesRegex(SettingsError, "stop_loss_pct is missing"):
            self._load_with("stop_loss_pct = 5.0\n", "")


class EnvStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = Path(self.tmp.name) / ".env"
        self.env.write_text("# my comment\nSCHWAB_APP_KEY=abc\nSCHWAB_APP_SECRET=\"s3 cr#t\"\nSCHWAB_TOKEN=\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_update_preserves_other_lines(self):
        envstore.update_env({"SCHWAB_ACCOUNT_HASH": "HASH123"}, self.env)
        text = self.env.read_text()
        self.assertIn("# my comment", text)
        self.assertIn("SCHWAB_APP_KEY=abc", text)
        vals = envstore.read_env(self.env)
        self.assertEqual(vals["SCHWAB_APP_SECRET"], "s3 cr#t")
        self.assertEqual(vals["SCHWAB_ACCOUNT_HASH"], "HASH123")

    def test_token_round_trip(self):
        tok = {"creation_timestamp": 1700000000,
               "token": {"access_token": "a", "refresh_token": "r=+/", "expires_in": 1800}}
        envstore.write_token(tok, self.env)
        self.assertEqual(envstore.read_token(self.env), tok)
        # stored on one line, not as readable JSON
        self.assertNotIn("refresh_token", self.env.read_text())
        envstore.clear_token(self.env)
        self.assertIsNone(envstore.read_token(self.env))

    def test_awkward_values_are_quoted(self):
        envstore.update_env({"X": 'has "quotes" and spaces'}, self.env)
        self.assertEqual(envstore.read_env(self.env)["X"], 'has "quotes" and spaces')

    @unittest.skipIf(os.name == "nt", "POSIX permissions")
    def test_permissions_are_owner_only(self):
        os.chmod(self.env, 0o644)
        envstore.update_env({"A": "1"}, self.env)
        self.assertTrue(envstore.permissions_ok(self.env))

    def test_rejects_bad_key(self):
        with self.assertRaises(ValueError):
            envstore.update_env({"BAD KEY": "x"}, self.env)


class EventLogTests(unittest.TestCase):
    def test_events_written_and_secrets_scrubbed(self):
        with tempfile.TemporaryDirectory() as d:
            logdir = Path(d)
            eventlog.setup_logging(logdir, console=False)
            try:
                eventlog.log_event("signal", "breakout", symbol="ABCD", price=4.12)
                eventlog.log_event("auth", "tok", access_token="SHOULD-NOT-APPEAR")
                try:
                    raise RuntimeError("boom")
                except RuntimeError as e:
                    eventlog.log_error("order failed", e, symbol="ABCD")
                text = (logdir / "trader.log").read_text()
                lines = [json.loads(l) for l in (logdir / "events.jsonl").read_text().splitlines()]
            finally:
                eventlog.setup_logging(Path(d) / "other", console=False)  # release handles
        self.assertNotIn("SHOULD-NOT-APPEAR", text)
        self.assertEqual([l["kind"] for l in lines], ["signal", "auth", "error"])
        self.assertEqual(lines[0]["details"]["symbol"], "ABCD")
        self.assertIn("boom", lines[2]["exception"])
        with self.assertRaises(ValueError):
            eventlog.log_event("not-a-kind", "x")


class SchwabAuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = Path(self.tmp.name) / ".env"
        self.env.write_text("SCHWAB_APP_KEY=key\nSCHWAB_APP_SECRET=sec\n"
                            "SCHWAB_CALLBACK_URL=https://127.0.0.1:8182\n")
        eventlog.setup_logging(Path(self.tmp.name) / "logs", console=False)

    def tearDown(self):
        self.tmp.cleanup()

    def test_callback_url_checks(self):
        self.assertEqual(schwab_auth.check_callback_url("https://127.0.0.1:8182", False), [])
        self.assertTrue(schwab_auth.check_callback_url("https://localhost:8182", False))
        self.assertTrue(schwab_auth.check_callback_url("https://127.0.0.1", False))
        self.assertTrue(schwab_auth.check_callback_url("http://127.0.0.1:8182", True))
        self.assertEqual(schwab_auth.check_callback_url("https://example.com/cb", True), [])

    def test_missing_credentials(self):
        self.env.write_text("SCHWAB_APP_KEY=key\n")
        with self.assertRaisesRegex(schwab_auth.AuthError, "SCHWAB_APP_SECRET"):
            schwab_auth.load_credentials(self.env)
        with self.assertRaisesRegex(schwab_auth.AuthError, "No .env"):
            schwab_auth.load_credentials(Path(self.tmp.name) / "nope")

    def test_token_age(self):
        now = time.time()
        left = schwab_auth.token_seconds_left({"creation_timestamp": now - 86400}, now)
        self.assertAlmostEqual(left, 6 * 86400)
        self.assertIsNone(schwab_auth.token_seconds_left(None))

    def test_get_client_requires_fresh_token(self):
        with self.assertRaisesRegex(schwab_auth.AuthError, "auth login"):
            schwab_auth.get_client(self.env)
        envstore.write_token({"creation_timestamp": time.time() - 8 * 86400, "token": {}}, self.env)
        with self.assertRaisesRegex(schwab_auth.AuthError, "expired"):
            schwab_auth.get_client(self.env)

    def _fake_schwab(self):
        calls = {}
        fake_auth = types.SimpleNamespace()

        def from_access_functions(key, secret, token_read_func, token_write_func):
            calls.update(key=key, secret=secret, read=token_read_func, write=token_write_func)
            return "CLIENT"

        def from_login_flow(key, secret, cb, token_path, token_write_func, interactive):
            calls.update(token_path=token_path)
            token_write_func({"creation_timestamp": int(time.time()), "token": {"access_token": "new"}})
            return "LOGIN-CLIENT"

        fake_auth.client_from_access_functions = from_access_functions
        fake_auth.client_from_login_flow = from_login_flow
        mod = types.ModuleType("schwab")
        mod.auth = fake_auth
        return calls, {"schwab": mod, "schwab.auth": fake_auth}

    def test_tokens_only_ever_go_to_dotenv(self):
        calls, modules = self._fake_schwab()
        with mock.patch.dict(sys.modules, modules):
            self.assertEqual(schwab_auth.login(env_path=self.env), "LOGIN-CLIENT")
            self.assertNotEqual(Path(calls["token_path"]).resolve(), self.env.resolve())
            self.assertFalse(Path(calls["token_path"]).exists())
            self.assertEqual(envstore.read_token(self.env)["token"]["access_token"], "new")

            self.assertEqual(schwab_auth.get_client(self.env), "CLIENT")
            self.assertEqual((calls["key"], calls["secret"]), ("key", "sec"))
            # a refresh by schwab-py lands back in .env
            calls["write"]({"creation_timestamp": 1, "token": {"access_token": "refreshed"}})
            self.assertEqual(calls["read"]()["token"]["access_token"], "refreshed")
        # app key/secret untouched by token writes
        self.assertEqual(envstore.read_env(self.env)["SCHWAB_APP_KEY"], "key")

    def test_list_accounts_masks_number(self):
        class Resp:
            def __init__(self, data): self.data = data
            def raise_for_status(self): pass
            def json(self): return self.data

        class Client:
            def get_account_numbers(self):
                return Resp([{"accountNumber": "12345678", "hashValue": "H1"}])

            def get_account(self, h):
                return Resp({"securitiesAccount": {
                    "type": "CASH", "isClosingOnlyRestricted": False,
                    "currentBalances": {"cashBalance": 1000.0, "cashAvailableForTrading": 800.0,
                                        "unsettledCash": 200.0}}})

        [a] = schwab_auth.list_accounts(Client())
        self.assertEqual(a["masked_number"], "****678")
        self.assertEqual(a["type"], "CASH")
        self.assertEqual(a["cash_available_for_trading"], 800.0)
        self.assertNotIn("12345678", json.dumps(a))


if __name__ == "__main__":
    unittest.main()
