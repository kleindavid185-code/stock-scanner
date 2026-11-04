# tradebot: strategy research, backtesting and Schwab execution

A self-contained trading bot that:

1. **Backtests** daily-bar stock/ETF strategies with realistic fills (signal at the close, fill at the next open, with slippage) and no look-ahead bias.
2. **Keeps searching for new strategies.** It randomly samples parameter sets across six strategy families and logs every trial forever. Only strategies that pass statistical tests against overfitting are kept.
3. **Forward-tests survivors on paper** against live quotes. Strategies that fail are retired automatically.
4. **Trades live through your Charles Schwab account** (Schwab Trader API), but only strategies you approve, inside hard risk limits.

This lives apart from the scanner web app on purpose. The multi-user web server stays read-only and never holds trading credentials.

---

## Read this first: what "profitable" realistically means

No one can honestly promise a profitable bot, including me. These are the facts that shaped the design:

- **Most retail algorithmic traders lose money.** Usually the cause is not bad code. It is strategies that were *overfit*: tuned until they looked great on past data, then failing live. Research on backtest overfitting (Bailey, Borwein, López de Prado & Zhu, 2014) shows that if you try enough variations, a "great" backtest is close to guaranteed even when no edge exists.
- **An edge needs a reason to exist.** The effects with the longest out-of-sample record on liquid assets are:
  - trend / time-series momentum (Moskowitz, Ooi & Pedersen 2012; Hurst, Ooi & Pedersen's century of evidence);
  - cross-sectional momentum (Jegadeesh & Titman 1993);
  - short-horizon mean reversion in assets already in an uptrend.

  These are the families this bot searches. They are well known, so returns are modest (think Sharpe 0.5–1.0, not 3+). They also go through multi-year stretches of underperforming buy-and-hold.
- **Risk management matters more than signal cleverness.** Three things do most of the work:
  - position caps;
  - volatility targeting (Moreira & Muir 2017, *Volatility-Managed Portfolios*);
  - drawdown kill switches.

  All three are built in.
- **Costs eat high-frequency strategies.** Schwab equity commissions are $0, but the bid/ask spread and slippage are not. Retail bots also cannot compete with HFT firms on speed. So this bot trades daily bars, rebalances once a day, uses a no-trade band to avoid churn, and models 5 bps of slippage per side. Raise that to 20–50 bps if you trade small caps.
- **Taxes.** In a taxable account, frequent trading turns gains into short-term capital gains. Consider running it in an IRA.

**How it guards against fooling itself**

| Guard | What it does |
|---|---|
| Untouched holdout | The most recent 2 years are never seen by the optimizer. Only finalists are tested on them, once. |
| Walk-forward optimization | It picks parameters on a past window and measures them on the next window, repeated across history. This tests the selection *process* itself. |
| Deflated Sharpe Ratio (Bailey & López de Prado 2014) | Corrects for how many strategies were tried. The trial count is cumulative across all runs, so "search until something looks lucky" is penalised. Trials are grouped by family, and the pass bar is tightened for the number of families searched (Šidák correction). |
| Parameter robustness | Neighbouring parameter values must work too. A lone spike is rejected. |
| Minimums | At least 30 trades and a maximum drawdown of 30%. |
| Paper trading | At least 40 trading days on live data before a strategy *can* be approved for live. |
| Live monitoring | A strategy is auto-retired if its live/paper drawdown exceeds 1.5× its backtest maximum drawdown. |

The test suite checks this machinery both ways. On a pure random-walk market (no edge exists), discovery promotes **nothing**. On a market with a planted trend effect, it finds the trend strategies and rejects the mean-reversion ones.

> These checks reduce the odds of trading a fluke. They do not remove them, and past performance does not guarantee future results. Start with money you can afford to lose.

---

## Strategy lifecycle

```
discover ──► rejected
    │
    ▼
candidate ──(auto, best per family first)──► paper ──(40+ days OK, YOU run `approve`)──► live
                                                 │                                         │
                                                 └──── auto-retire on excessive drawdown ◄─┘
```

Live capital is split equally across approved strategies, and their target weights are summed. Holding several uncorrelated strategies is one of the few reliable ways to smooth returns.

## Strategy families

| Family | Idea | Main parameters |
|---|---|---|
| `trend_sma` | Hold assets above their N-day moving average | sma, rebalance |
| `ts_momentum` | Hold assets with positive trailing return | lookback, rebalance |
| `xs_momentum` | Rotate into the top-K performers (optional 1-month skip and absolute filter) | lookback, skip, rebalance |
| `rsi_reversion` | Buy RSI(2–4) dips in uptrends, exit on rebound or time stop | rsi_len, entry, exit, trend_sma, max_hold |
| `bollinger_reversion` | Buy z-score < −k in uptrends | window, entry_z, exit_z |
| `donchian_breakout` | Buy N-day highs, exit at M-day lows | entry_n, exit_n |

**Day-trading families** buy at the open and sell at the close, so they hold nothing overnight. They're searched with `tradebot discover --daytrade`:

| Family | Idea |
|---|---|
| `day_gap_fade` | Buy a gap down at the open (gaps in liquid names often partly fill) |
| `day_gap_go` | Buy a gap up at the open (tests gap continuation) |
| `day_reversal` | Buy the open after a big down day |
| `day_rsi` | Buy the open when prior-close RSI(2–4) is oversold |
| `day_always` | Baseline: buy every open, sell every close. Shows how much of the market's return happens during the day vs overnight. |

They can only use information available at the open, and a test checks this. Slippage is charged on both sides every day. For now they're research-only: they're never promoted to paper or live, because same-day execution isn't built yet. Be aware of the pattern-day-trader rule ($25,000 minimum in a margin account) and of T+1 settlement in cash accounts.

**Intraday families (5-minute bars)** open and close trades during the session. They're searched with `tradebot discover --intraday`:

| Family | Research it's based on | Idea |
|---|---|---|
| `intraday_orb` | Zarattini, Barbon & Aziz (2023) | Opening-range breakout: trade in the direction of the first 5/15/30 minutes, stop at the other side of the range, optional profit target, otherwise exit at the close |
| `intraday_momentum` | Gao, Han, Li & Zhou (2018, *JFE*) | The return from the prior close to 10:00 predicts the last half hour; enter at 15:00 or 15:30, exit at the close |
| `intraday_noise` | Zarattini, Aziz & Barbon (2024) | Enter only on breaks outside the usual intraday "noise band" for that time of day; trail with the band or VWAP |

5-minute history comes free from Alpaca, going back to 2016. Use the same `ALPACA_API_KEY` / `ALPACA_API_SECRET` as the scanner app, in `trading-bot/.env`. Only market-data endpoints are called. Downloads are cached per symbol per year in `data/cache/alpaca_5min/`. A test checks that strategies never use prices from after the moment they enter. These strategies are research-only for now, like the daily-bar day-trade families.

Notes on the published versions of these strategies:
- Their headline results often rely on leverage (2–4×) and very low costs. This bot uses no leverage, and costs are set with `--slippage-bps`.
- For SPY, 1–2 bps per side is realistic for small orders. Results are very sensitive to this number, so test several values.

Every swing family also searches `max_positions`, `sizing` (`equal` or `inverse_vol`) and `vol_target` (0, 12% or 18%). To add a family, subclass `Strategy` in `tradebot/strategies/library.py` and register it in `STRATEGIES`. Discovery picks it up automatically.

---

## Setup

### 1. Install (Python 3.11+)

```bash
cd trading-bot
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp config.example.toml config.toml
cp .env.example .env && chmod 600 .env
tradebot demo        # end-to-end run on synthetic data, no keys needed
pytest -q            # 68 tests
```

### Backtest on real data tonight (no Schwab account needed)

Add `--source yahoo` to use free Yahoo Finance history. It's adjusted for dividends and splits, so it's good for research:

```bash
tradebot backtest trend_sma --source yahoo --params '{"sma": 200}'
tradebot discover --source yahoo
tradebot strategies --verbose

# Day trading (buy open, sell close), compared against buy & hold in dollars:
tradebot backtest day_always --source yahoo --symbols SPY
tradebot discover --daytrade --source yahoo

# Intraday on 5-minute bars (needs free Alpaca keys in .env):
tradebot backtest intraday_momentum --symbols SPY --slippage-bps 1
tradebot discover --intraday --symbols SPY QQQ IWM --slippage-bps 1
```

Yahoo is an unofficial source and occasionally rate-limits; the bot retries automatically. Use Schwab data for live trading.

### 2. Get Schwab API access

1. Go to <https://developer.schwab.com>, sign in with your Schwab login, and create an app. Request **Accounts and Trading Production** and **Market Data Production**.
2. Set the callback URL to `https://127.0.0.1:8182` (it must match `.env` exactly).
3. Wait until the app status is **Ready For Use**. Approval can take a few days.
4. Put the App Key and Secret into `.env`. **Do not paste them into chats, issues or commits.** Nobody, including an AI assistant, needs them. The bot reads them locally.

### 3. Log in and check the account

```bash
tradebot auth          # prints a Schwab login URL; paste back the redirect URL
tradebot accounts      # shows account hash(es) and balances
```

If you have several accounts, set `SCHWAB_ACCOUNT_HASH` in `.env`.

⚠️ **Schwab refresh tokens expire every 7 days.** Run `tradebot auth --force` weekly. The bot logs a warning after 6 days. If it expires, the bot stops trading; it does not trade blindly.

### 4. Research

```bash
tradebot fetch                                 # downloads ~20y daily history into data/cache
tradebot backtest trend_sma --params '{"sma": 200}' --out reports/sma200
tradebot discover --trials 300                 # one search run
tradebot strategies --verbose                  # see what passed and why others failed
```

### 5. Paper trade (at least 2 months)

```bash
tradebot run --mode paper --dry-run            # show the orders it would place
tradebot daemon --mode paper                   # rebalance 09:45 ET daily, review/discover at 18:00 ET
tradebot status
```

Paper mode uses real Schwab quotes and the real market calendar once you're authenticated. Schwab has no paper-trading API, so fills are simulated, slightly pessimistically.

### 6. Go live, small

1. Wait until `tradebot strategies` shows a paper strategy with 40+ forward days. You'll also get a log/webhook message saying it is eligible.
2. Set `[risk] bot_capital` to an amount you can afford to lose. The bot never controls more than this.
3. Set `[execution] live_trading_enabled = true` in `config.toml`.
4. Set `TRADEBOT_LIVE_CONFIRM=I_UNDERSTAND_THIS_TRADES_REAL_MONEY` in `.env`. Both interlocks are required.
5. Run `tradebot approve <id>`.
6. Run `tradebot run --mode live --dry-run` and check the orders.
7. Run `tradebot daemon --mode live`.

**Emergency stop:** run `tradebot kill`, or `touch state/KILL`. Both halt all orders immediately. To resume, run `tradebot kill --reset --mode live`.

### Running unattended

Use a small always-on machine or VPS in a US timezone. Example systemd unit:

```ini
[Service]
WorkingDirectory=/home/you/stock-scanner/trading-bot
ExecStart=/home/you/stock-scanner/trading-bot/.venv/bin/tradebot daemon --mode live
Restart=on-failure
```

Set `TRADEBOT_WEBHOOK_URL` to a Slack or Discord webhook to get fill, error and promotion alerts on your phone.

---

## Risk controls (all in `config.toml [risk]`)

| Control | Default | Behaviour |
|---|---|---|
| `bot_capital` | $10,000 | The bot has its own cash book. It only buys with that and only sells shares it bought, so your other holdings are never touched. |
| `max_position_pct` | 20% | Cap per symbol |
| `max_gross_exposure` | 1.0 | No leverage |
| `long_only` | true | No shorting |
| `min_price` / `min_dollar_volume` | $5 / $20M | Skips penny stocks and illiquid names |
| `daily_loss_limit_pct` | 4% | No new buys for the rest of the day after a bad day |
| `max_drawdown_kill_pct` | 20% | Liquidates the bot's positions and stops until you reset |
| `max_orders_per_run` | 30 | Guards against runaway loops |
| Limit-order collar | 0.30% | Buys at ask + 0.3%, sells at bid − 0.3%. Unfilled orders are cancelled after 120s. |
| Data staleness | — | Refuses to trade if the latest bar is more than 5 days old |
| Idempotency | — | Only one rebalance per day per mode |

## Things to know

- **Survivorship bias.** A universe of *today's* big winners (AAPL, NVDA, …) makes backtests look better than reality. ETFs are less affected. Be sceptical of stock-heavy results.
- **Dividends.** Schwab's daily history may not be dividend-adjusted. That understates returns for income ETFs like TLT. For research you can use `--source yahoo` (or `data.source = "yahoo"`), which is adjusted, and Schwab for live trading. Each source has its own cache folder, so the two never mix.
- **Cash accounts and T+1 settlement.** Buying with unsettled sale proceeds can trigger good-faith violations. A margin-enabled account avoids this (the bot still never uses leverage). The bot always sells before it buys.
- **Pattern day trading.** The bot rebalances once per day and holds overnight, so it doesn't day-trade.
- **Whole shares only.** The Schwab API doesn't support fractional shares, so small `bot_capital` with many positions leaves some cash idle.
- **What the backtest doesn't model:** the price impact of large orders, borrow costs, halts, and the small timing gap between the open and the 09:45 run.

## Layout

```
tradebot/
  config.py            settings (config.toml) + secrets (.env) + live interlock
  data/                Schwab / Yahoo / CSV / synthetic providers, CSV cache
  indicators.py        SMA, RSI, z-score, vol, ATR ... (causal only)
  strategies/          Strategy base class + 6 families
  backtest/            share-level simulator + metrics
  research/            Deflated Sharpe, walk-forward, discovery engine
  broker/              PaperBroker, SchwabBroker
  execution/           RiskManager, order planner
  live/runner.py       rebalance, forward-test review, daemon
  store.py             SQLite: registry, trial log, ledger, orders, equity
  cli.py               `tradebot ...` commands
tests/                 look-ahead, costs, cash limits, DSR, discovery power, risk, Schwab fake
```
