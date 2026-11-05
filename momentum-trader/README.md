# Momentum Trader

A standalone intraday trading bot for low-priced, high-volatility momentum
stocks, trading a **Charles Schwab cash account** through the Schwab Trader API.

This folder is completely separate from the watch-only scanner in the rest of
this repo. It has its own settings, secrets, logs, and dashboard port (5055),
and it does not import, read, or modify anything outside `momentum-trader/`.

> **Risk warning.** Low-float momentum stocks move fast, halt, and gap. This
> bot can lose money, including all of the money you let it trade. Run it in
> `dryrun` mode for a long time before giving it real orders, and keep the
> risk limits small.

---

## Build status

| Phase | What | Status |
|---|---|---|
| 1 | Project setup, Schwab OAuth, tokens in `.env` | **done, awaiting review** |
| 2 | Real-time data + scanner + Flask dashboard (port 5055) | not started |
| 3 | Strategy + Lean backtest + report | not started |
| 4 | Dry-run mode (orders generated and logged, never sent) | not started |
| 5 | Live with manual approval (click to approve each order) | not started |
| 6 | Fully automatic mode (off by default) | not started |

---

## Safety rules built into the design

These are **not** settings you can turn off:

* **Limit orders only.** The order builder will not have a market-order code path.
* **Settled cash only.** Buys are sized from settled funds so a cash account
  never takes a good-faith violation.
* **Flat by end of day.** At `flatten_at`, everything is cancelled and sold.
* **Read-only settings.** `settings.toml` is loaded once into read-only objects;
  the strategy has no way to loosen a risk limit while running.
* **Two switches for auto trading.** `mode = "auto"` *and*
  `auto_trading_enabled = true` are both required.
* **Secrets stay in `.env`.** `.env` is git-ignored, written with owner-only
  permissions, and the token is never printed or logged.

---

## Phase 1 setup (one time)

### 1. Create a Schwab developer app

1. Go to <https://developer.schwab.com> and sign up. This is a separate login
   from your brokerage login.
2. **Dashboard → Apps → Create App.**
   * API products: **Accounts and Trading Production** and **Market Data Production**.
   * Callback URL: `https://127.0.0.1:8182` (exactly, including `https` and the port).
3. Wait for the app status to change to **Ready For Use**. Schwab reviews new
   apps by hand, which can take a few days.
4. Open the app and copy its **App Key** and **Secret**.

### 2. Install Python packages

You need Python 3.11 or newer.

```bash
cd momentum-trader
python3 -m venv .venv            # private Python environment for this bot only
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt  # schwab-py + python-dotenv
```

### 3. Add your keys

```bash
cp .env.example .env
chmod 600 .env                   # macOS/Linux: only you can read it
```

Edit `.env` and fill in `SCHWAB_APP_KEY`, `SCHWAB_APP_SECRET`, and
`SCHWAB_CALLBACK_URL`. Leave `SCHWAB_TOKEN` and `SCHWAB_ACCOUNT_HASH` blank;
the login command fills them in.

### 4. Log in

```bash
python trader.py auth login
```

The command opens your browser to Schwab's login page. Your browser will warn
that the `127.0.0.1` page is "not secure". That is expected: the bot runs a
temporary local page with a self-signed certificate just to catch Schwab's
redirect. Log in, tick your cash account, and click **Allow**. The bot saves
the token to `.env` and asks which account to trade.

If the browser flow doesn't work, use the copy-paste flow:

```bash
python trader.py auth login --manual
```

### 5. Check it

```bash
python trader.py auth status
```

This confirms that `.env` is git-ignored and private, shows how long until
the token expires, and makes one **read-only** API call. That call shows the
account type (it should say `CASH`), settled cash available to trade, and
unsettled cash.

### Weekly re-login (Schwab rule)

Schwab refresh tokens last **7 days** and cannot be extended. Run
`python trader.py auth login` once a week. `auth status` shows the time left,
and the bot logs a warning when less than a day remains.

### Other commands

```bash
python trader.py settings        # validate settings.toml and print a summary
python trader.py auth logout     # delete the saved token from .env
python -m unittest discover -s tests -v   # run the test suite
```

---

## Settings

Everything tunable lives in **`settings.toml`**: scanner filters, entry and exit
rules, risk limits, and backtest assumptions. Each line is commented. After
editing, run `python trader.py settings`. It refuses unsafe or mistyped values,
for example a negative loss limit, `flatten_at` after 16:00, or an unknown key.

## Logs

Every signal, order, fill, and error is written to:

* `logs/trader.log`: one readable line per event
* `logs/events.jsonl`: one JSON object per line, for later analysis

Both files rotate daily and are kept for 90 days. They are git-ignored.

## Project layout

```
momentum-trader/
  trader.py                 command line (all modes start here)
  settings.toml             the one settings file
  .env.example              template for secrets (.env itself is git-ignored)
  requirements.txt
  momentum_trader/
    settings.py             load + validate settings (read-only once loaded)
    envstore.py             safe .env reads/writes, token storage
    schwab_auth.py          Schwab OAuth via schwab-py, account info (read-only)
    eventlog.py             signal/order/fill/error logging
    paths.py                file locations (all inside this folder)
  tests/
  logs/  data/              runtime output (git-ignored)
```

## Running each mode

These sections are filled in as each phase is built and approved.

* **Scanner + dashboard** (Phase 2): not built yet
* **Backtest** (Phase 3): not built yet
* **Dry run** (Phase 4): not built yet
* **Manual approval** (Phase 5): not built yet
* **Automatic** (Phase 6): not built yet
* **Kill switch**: not built yet (arrives with Phase 4, before any live orders exist)
