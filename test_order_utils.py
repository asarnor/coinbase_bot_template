import order_utils


class FakeExchange:
    def __init__(self, status="open", cancel_raises=False, fetch_order_raises=False):
        self.status = status
        self.cancel_raises = cancel_raises
        self.fetch_order_raises = fetch_order_raises
        self.limit_buy_calls = []
        self.market_buy_calls = []
        self.cancel_calls = []

    def fetch_ticker(self, symbol):
        return {"last": 100.0}

    def create_limit_buy_order(self, symbol, amount, price):
        self.limit_buy_calls.append((symbol, amount, price))
        return {"id": "order-1"}

    def fetch_order(self, order_id, symbol):
        if self.fetch_order_raises:
            raise RuntimeError("status unavailable")
        return {"status": self.status}

    def cancel_order(self, order_id, symbol):
        self.cancel_calls.append((order_id, symbol))
        if self.cancel_raises:
            raise RuntimeError("cancel failed")
        return {"id": order_id}

    def create_market_buy_order(self, symbol, cost):
        self.market_buy_calls.append((symbol, cost))
        return {"id": "market-1"}


def test_unfilled_limit_entry_is_canceled_without_market_fallback(monkeypatch):
    monkeypatch.setattr(order_utils.time, "sleep", lambda _: None)
    exchange = FakeExchange(status="open")

    executed = order_utils.place_entry_order(
        exchange,
        "ETH/USD",
        "ETH",
        amount=0.5,
        cost=50.0,
        use_limit_orders=True,
        limit_order_offset_pct=0.001,
        enable_trading=True,
    )

    assert executed is False
    assert exchange.limit_buy_calls == [("ETH/USD", 0.5, 99.9)]
    assert exchange.cancel_calls == [("order-1", "ETH/USD")]
    assert exchange.market_buy_calls == []


def test_uncancelable_limit_entry_is_tracked_as_executed(monkeypatch):
    monkeypatch.setattr(order_utils.time, "sleep", lambda _: None)
    exchange = FakeExchange(status="open", cancel_raises=True)

    executed = order_utils.place_entry_order(
        exchange,
        "ETH/USD",
        "ETH",
        amount=0.5,
        cost=50.0,
        use_limit_orders=True,
        limit_order_offset_pct=0.001,
        enable_trading=True,
    )

    assert executed is True
    assert exchange.cancel_calls == [("order-1", "ETH/USD")]
    assert exchange.market_buy_calls == []


def test_unverifiable_limit_entry_is_tracked_as_executed(monkeypatch):
    monkeypatch.setattr(order_utils.time, "sleep", lambda _: None)
    exchange = FakeExchange(fetch_order_raises=True)

    executed = order_utils.place_entry_order(
        exchange,
        "ETH/USD",
        "ETH",
        amount=0.5,
        cost=50.0,
        use_limit_orders=True,
        limit_order_offset_pct=0.001,
        enable_trading=True,
    )

    assert executed is True
    assert exchange.cancel_calls == []
    assert exchange.market_buy_calls == []
