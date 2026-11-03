# Stock scanner — next up

## Backtesting harness / trading bot (see trading-bot/README.md)
- [x] Strategy definition format + scoring (DSR, walk-forward, holdout)
- [x] Paper trading (built-in paper broker; Schwab has no paper API)
- [x] Compare strategies side by side (`tradebot strategies`)
- [ ] Run `tradebot fetch` + `discover` on real Schwab data and review results
- [ ] Paper trade >= 40 trading days before approving anything live
- [ ] Optional: surface `tradebot` registry/equity in the web app (read-only)

## Signals / expected ranges
- [ ] Show the expected range (ATR-based today/tomorrow high-low)
      on Scanner and Watchlist rows too, not just the Signals page
