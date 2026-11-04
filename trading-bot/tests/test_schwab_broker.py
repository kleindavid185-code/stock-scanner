"""SchwabBroker against a fake client (no network)."""
from types import SimpleNamespace

from tradebot.broker.base import OrderRequest
from tradebot.broker.schwab_broker import SchwabBroker


class Resp:
    def __init__(self, data=None, status=200, headers=None):
        self._d, self.status_code, self.headers = data, status, headers or {}
        self.text = str(data)
        self.is_error = status >= 400

    def json(self):
        return self._d

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeClient:
    Account = SimpleNamespace(Fields=SimpleNamespace(POSITIONS="positions"))
    MarketHours = SimpleNamespace(Market=SimpleNamespace(EQUITY="equity"))

    def __init__(self, final_status="FILLED"):
        self.final_status = final_status
        self.placed = []
        self.canceled = []

    def get_account_numbers(self):
        return Resp([{"accountNumber": "12345678", "hashValue": "HASH"}])

    def get_account(self, h, fields=None):
        return Resp({"securitiesAccount": {"type": "MARGIN", "currentBalances": {
            "liquidationValue": 50000.0, "availableFunds": 20000.0},
            "positions": [{"longQuantity": 10, "shortQuantity": 0,
                           "instrument": {"symbol": "SPY", "assetType": "COLLECTIVE_INVESTMENT"}},
                          {"longQuantity": 1, "shortQuantity": 0,
                           "instrument": {"symbol": "SPY 250117C00500000", "assetType": "OPTION"}}]}})

    def get_quotes(self, syms):
        return Resp({s: {"quote": {"bidPrice": 99.9, "askPrice": 100.1, "lastPrice": 100.0}} for s in syms})

    def get_market_hours(self, markets, date=None):
        return Resp({"equity": {"EQ": {"isOpen": True}}})

    def place_order(self, h, spec):
        self.placed.append(spec.build())
        return Resp(None, 201, {"Location": "https://api.schwabapi.com/trader/v1/accounts/HASH/orders/987"})

    def get_order(self, oid, h):
        if self.final_status == "FILLED":
            return Resp({"status": "FILLED", "filledQuantity": 5, "orderActivityCollection": [
                {"executionLegs": [{"quantity": 2, "price": 100.0}, {"quantity": 3, "price": 101.0}]}]})
        return Resp({"status": "WORKING", "filledQuantity": 0})

    def cancel_order(self, oid, h):
        self.canceled.append(oid)
        self.final_status = "CANCELED"
        return Resp(None, 200)


def test_account_and_positions_parsing():
    b = SchwabBroker(FakeClient())
    assert b.account_hash == "HASH"
    assert b.account_summary()["cash_available"] == 20000.0
    assert b.broker_positions() == {"SPY": 10.0}  # options ignored
    assert b.quotes(["SPY"])["SPY"].mid == 100.0
    assert b.is_market_open(__import__("datetime").date(2025, 1, 2))


def test_limit_order_filled_with_avg_price():
    c = FakeClient()
    res = SchwabBroker(c).submit(OrderRequest("SPY", "BUY", 5, "limit", 100.4))
    assert res.status == "FILLED" and res.filled_qty == 5
    assert abs(res.avg_price - 100.6) < 1e-9
    o = c.placed[0]
    assert o["orderType"] == "LIMIT" and o["price"] == "100.40"
    assert o["orderLegCollection"][0]["instruction"] == "BUY"


def test_unfilled_order_is_canceled_after_timeout():
    c = FakeClient(final_status="WORKING")
    b = SchwabBroker(c, fill_timeout_sec=0)
    res = b.submit(OrderRequest("SPY", "SELL", 5, "limit", 99.0))
    assert c.canceled == ["987"] and res.filled_qty == 0
