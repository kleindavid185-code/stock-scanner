"""Charles Schwab Trader API broker (via schwab-py).

Auth: Schwab uses OAuth. `tradebot auth` walks you through login once and writes
a token file; schwab-py refreshes the 30-minute access token automatically, but
the refresh token expires after 7 days, so re-run `tradebot auth` weekly.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import date

from .base import Broker, OrderRequest, OrderResult, Quote

log = logging.getLogger(__name__)


def make_schwab_client(cfg, interactive: bool = False):
    try:
        from schwab import auth
    except ImportError as exc:
        raise RuntimeError("pip install schwab-py") from exc
    cred = cfg.schwab
    if not cred.configured:
        raise RuntimeError("Set SCHWAB_APP_KEY and SCHWAB_APP_SECRET in .env (see .env.example)")
    if not cred.token_path.exists():
        if not interactive:
            raise RuntimeError("No Schwab token yet -- run `tradebot auth` first")
        cred.token_path.parent.mkdir(parents=True, exist_ok=True)
        return auth.client_from_manual_flow(cred.app_key, cred.app_secret, cred.callback_url,
                                            str(cred.token_path))
    warn_token_age(cred.token_path)
    return auth.client_from_token_file(str(cred.token_path), cred.app_key, cred.app_secret)


def token_age_days(token_path) -> float | None:
    try:
        meta = json.loads(open(token_path).read())
        ts = meta.get("creation_timestamp")
        return (time.time() - ts) / 86400 if ts else None
    except Exception:
        return None


def warn_token_age(token_path) -> None:
    age = token_age_days(token_path)
    if age is not None and age > 6:
        log.warning("Schwab refresh token is %.1f days old and expires at 7 days -- run `tradebot auth` NOW", age)


class SchwabBroker(Broker):
    mode = "live"

    def __init__(self, client, account_hash: str | None = None, fill_timeout_sec: int = 120):
        self.c = client
        self.fill_timeout = fill_timeout_sec
        self.account_hash = account_hash or self._single_account_hash()

    # ---- account --------------------------------------------------------
    def account_numbers(self) -> list[dict]:
        r = self.c.get_account_numbers()
        r.raise_for_status()
        return r.json()

    def _single_account_hash(self) -> str:
        accts = self.account_numbers()
        if len(accts) != 1:
            raise RuntimeError(f"{len(accts)} accounts found; set SCHWAB_ACCOUNT_HASH (see `tradebot accounts`)")
        return accts[0]["hashValue"]

    def _account(self) -> dict:
        r = self.c.get_account(self.account_hash, fields=[self.c.Account.Fields.POSITIONS])
        r.raise_for_status()
        return r.json()["securitiesAccount"]

    def account_summary(self) -> dict:
        a = self._account()
        bal = a.get("currentBalances", {})
        cash_avail = bal.get("cashAvailableForTrading")
        if cash_avail is None:  # margin accounts
            cash_avail = bal.get("availableFunds", bal.get("buyingPower", 0.0))
        return {"liquidation_value": float(bal.get("liquidationValue", 0.0)),
                "cash_available": float(cash_avail or 0.0), "type": a.get("type")}

    def broker_positions(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for p in self._account().get("positions", []):
            inst = p.get("instrument", {})
            if inst.get("assetType") not in ("EQUITY", "ETF", "COLLECTIVE_INVESTMENT"):
                continue
            qty = float(p.get("longQuantity", 0)) - float(p.get("shortQuantity", 0))
            out[inst["symbol"]] = out.get(inst["symbol"], 0.0) + qty
        return out

    # ---- market data ----------------------------------------------------
    def quotes(self, symbols: list[str]) -> dict[str, Quote]:
        out = {}
        for i in range(0, len(symbols), 200):
            chunk = symbols[i:i + 200]
            r = self.c.get_quotes(chunk)
            r.raise_for_status()
            for sym, d in r.json().items():
                q = d.get("quote", {})
                last = float(q.get("lastPrice") or q.get("closePrice") or 0)
                out[sym] = Quote(sym, float(q.get("bidPrice") or 0), float(q.get("askPrice") or 0), last)
        return out

    def is_market_open(self, day: date) -> bool:
        r = self.c.get_market_hours([self.c.MarketHours.Market.EQUITY], date=day)
        r.raise_for_status()
        for markets in r.json().values():
            for m in markets.values():
                if m.get("isOpen"):
                    return True
        return False

    # ---- orders ---------------------------------------------------------
    def submit(self, order: OrderRequest) -> OrderResult:
        from schwab.orders import equities as eq
        from schwab.utils import Utils

        try:
            if order.order_type == "limit" and order.limit_price:
                price = f"{order.limit_price:.2f}" if order.limit_price >= 1 else f"{order.limit_price:.4f}"
                spec = (eq.equity_buy_limit if order.side == "BUY" else eq.equity_sell_limit)(
                    order.symbol, order.qty, price)
            else:
                spec = (eq.equity_buy_market if order.side == "BUY" else eq.equity_sell_market)(
                    order.symbol, order.qty)
            resp = self.c.place_order(self.account_hash, spec)
            if resp.status_code not in (200, 201):
                return OrderResult(None, "REJECTED", error=f"HTTP {resp.status_code}: {resp.text[:300]}")
            oid = Utils(self.c, self.account_hash).extract_order_id(resp)
            if oid is None:
                return OrderResult(None, "ERROR", error="order placed but no id returned -- check Schwab manually")
            return self._wait(str(oid))
        except Exception as exc:  # never let one order crash the run
            log.exception("order failed")
            return OrderResult(None, "ERROR", error=str(exc))

    def _wait(self, oid: str) -> OrderResult:
        deadline = time.time() + self.fill_timeout
        last = {}
        while time.time() < deadline:
            r = self.c.get_order(oid, self.account_hash)
            r.raise_for_status()
            last = r.json()
            status = last.get("status")
            if status in ("FILLED", "REJECTED", "CANCELED", "EXPIRED"):
                break
            time.sleep(3)
        else:
            # Don't leave stale orders working: cancel what's unfilled.
            try:
                self.c.cancel_order(oid, self.account_hash)
                last = self.c.get_order(oid, self.account_hash).json()
            except Exception as exc:
                log.warning("cancel of %s failed: %s", oid, exc)
        filled = float(last.get("filledQuantity", 0) or 0)
        legs = [leg for act in last.get("orderActivityCollection", []) for leg in act.get("executionLegs", [])]
        q = sum(float(l["quantity"]) for l in legs)
        avg = sum(float(l["quantity"]) * float(l["price"]) for l in legs) / q if q else None
        status = last.get("status", "UNKNOWN")
        if status != "FILLED" and filled > 0:
            status = "PARTIAL"
        return OrderResult(oid, status, filled, avg, None if filled else last.get("statusDescription"))
