# Signal Engine

Drop-in module for your scanner app backend that turns price/volume bars into
technical indicators, then asks Claude to interpret them into a structured
bullish/bearish/neutral signal per symbol.

## Files

- **indicators.js** — pure functions: RSI, MACD, VWAP, ATR, relative volume,
  and a lightweight price-action classifier (breakout/breakdown/consolidation/trend).
  No dependencies, no API calls — just math on bar arrays.
- **claudeSignal.js** — sends one symbol's indicator bundle to Claude
  (`claude-sonnet-4-5`, matching your existing NL query integration) and
  parses back a structured JSON signal. Includes a batched helper with
  concurrency control for polling a whole watchlist without hammering the API.
- **signalRoute.js** — Express router + polling loop that wires the above
  together and exposes `GET /api/signals` and `GET /api/signals/:symbol`.

## Integration steps

1. Copy the `signal-engine/` folder into your existing backend repo.
2. Install the SDK if you haven't already: `npm install @anthropic-ai/sdk`
   (you likely already have this from your NL query box).
3. In **signalRoute.js**, replace `fetchBarsForSymbol` with a call into your
   existing Alpaca data layer. It needs to return:
   ```js
   {
     intraday: [...],           // today's bars, { t, o, h, l, c, v }
     daily: [...],               // enough historical daily/intraday bars for RSI/MACD/ATR (need 30+ points)
     avgBaselineVolume: number   // optional, for relative volume calc
   }
   ```
4. In your main server file:
   ```js
   const { router: signalRouter, startSignalPolling } = require("./signal-engine/signalRoute");

   app.use("/api/signals", signalRouter);

   // point this at whatever holds your current watchlist
   startSignalPolling(() => currentWatchlist, 60_000); // poll every 60s
   ```
5. In the app, add a "Signals" screen/tab that hits `GET /api/signals` and
   renders symbol, direction, confidence, reasoning, and key level to watch.

## Notes on accuracy and risk

- RSI/MACD/ATR need a real history (30+ bars minimum) to be meaningful —
  don't call this on a symbol with only a few minutes of intraday bars.
- VWAP is computed only over the bars you pass as `sessionBars` — pass just
  today's intraday bars, not the full daily history, or it won't reset
  properly each session.
- The Claude signal layer is intentionally conservative — it's prompted to
  say "neutral" on mixed signals rather than force a direction. That's a
  deliberate choice for a personal tool; loosen the system prompt in
  `claudeSignal.js` if you want it to take more decisive stances, but
  understand that increases false-positive risk.
- This is signal generation only — no order placement. Keep it that way
  unless you build a separate, deliberately gated execution layer with its
  own guardrails (position size caps, daily loss limits, manual confirm
  before any live order).
- Cost: each signal call is a small prompt (~500 tokens out). Polling a
  20-symbol watchlist every 60s is ~1,200 calls/hour — check that against
  your API usage/budget, and consider a longer poll interval (2-5 min) for
  a more relaxed watchlist size.
