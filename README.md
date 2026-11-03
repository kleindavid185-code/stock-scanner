# Market Scanner (personal, read-only)

A native mobile app (Expo/React Native) + backend that scans the market for
volume/momentum candidates, tracks custom watchlists, and shows quote
detail — using Alpaca's free market data API. **Read-only: no trading, no
order endpoints, no account/money access anywhere in the scanner app.**

> **Trading bot:** strategy backtesting, automated strategy discovery and
> Schwab order execution live in a separate, standalone package at
> [`trading-bot/`](trading-bot/README.md). It is deliberately isolated from
> this multi-user web app, which stays read-only.

## How it's scored

The "AI" part is a transparent scoring formula (see
`backend/src/scoring.js`) combining relative volume, % change, intraday
range, and gap %. It's a **screener that surfaces currently-active names**,
not a predictor of what will spike next — there's no reliable way to
predict that, and this app doesn't pretend to.

## 1. Get Alpaca API keys (free, data-only)

1. Sign up at https://alpaca.markets (paper/free account is fine — you
   never need to fund it or enable trading).
2. Go to your dashboard → generate an API key + secret.
3. Keep these private; they only grant market-data access here, but treat
   them like any other credential.

## 2. Run the backend

```bash
cd backend
cp .env.example .env
# edit .env and paste in your ALPACA_API_KEY / ALPACA_API_SECRET
npm install
npm start
```

The server runs on `http://localhost:4000` by default. Confirm it works:

```bash
curl http://localhost:4000/api/scan
```

## 3. Point the mobile app at your backend

Find your computer's LAN IP (so your phone can reach it over Wi-Fi):

- Mac: `ipconfig getifaddr en0`
- Windows: `ipconfig` (look for IPv4 Address)
- Linux: `hostname -I`

Edit `mobile/api/config.js` and set `API_BASE_URL` to
`http://<that-ip>:4000`.

## 4. Run the mobile app

```bash
cd mobile
npm install
npx expo start
```

Scan the QR code with the Expo Go app on your phone (same Wi-Fi network as
your computer), or press `i` / `a` in the terminal to open an iOS
Simulator / Android emulator if you have one set up.

## Project structure

```
backend/
  src/
    alpacaClient.js   # read-only Alpaca Market Data API calls only
    scoring.js         # the ranking/screener formula
    watchlistStore.js  # local JSON file storage (single user)
    server.js           # Express routes
mobile/
  screens/              # Scanner, Watchlists, WatchlistDetail, StockDetail
  api/client.js          # talks to your backend
  App.js                  # navigation
```

## Notes / next steps

- Free-tier Alpaca uses the IEX feed — real-time-ish but only ~2-5% of
  total consolidated market volume, so treat RVOL/volume numbers as
  directional, not exact. Upgrading to a paid real-time feed (e.g.
  Polygon.io Stocks Advanced, ~$199/mo) is a drop-in change: swap the
  base URL and auth in `alpacaClient.js` for the new provider.
- The `/api/scan` endpoint currently seeds from Alpaca's "most active" and
  "movers" screeners (~150 symbols) rather than the full ~11k-symbol
  market, since polling everything on the free tier would blow through
  rate limits. This is a very reasonable proxy for "what's active right
  now" but isn't literally the entire market.
- Scoring weights in `scoring.js` are a first-pass heuristic — tune them
  based on what you find actually correlates with the moves you care about.
- For continued development (adding charts, alerts, news integration,
  etc.), this is a good project to keep iterating on in Claude Code.
