import ast
import types
from pathlib import Path


def load_trading_helpers():
    source = Path("main_multi_symbol.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    wanted = {"place_entry_order", "place_exit_order", "get_position_size"}
    helper_nodes = [
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name in wanted
    ]
    namespace = {
        "Tuple": tuple,
        "time": types.SimpleNamespace(sleep=lambda _seconds: None),
    }
    compiled = compile(ast.Module(body=helper_nodes, type_ignores=[]), "main_multi_symbol.py", "exec")
    exec(compiled, namespace)
    return namespace


class FakeExchange:
    def __init__(self, order_status="open", fetch_order_error=None):
        self.order_status = order_status
        self.fetch_order_error = fetch_order_error
        self.cancelled_orders = []
        self.market_buys = []
        self.market_sells = []

    def fetch_ticker(self, _symbol):
        return {"last": 100.0}

    def create_limit_buy_order(self, _symbol, amount, price):
        self.limit_buy = {"amount": amount, "price": price}
        return {"id": "buy-1"}

    def create_limit_sell_order(self, _symbol, amount, price):
        self.limit_sell = {"amount": amount, "price": price}
        return {"id": "sell-1"}

    def fetch_order(self, order_id, _symbol):
        if self.fetch_order_error:
            raise self.fetch_order_error
        return {"id": order_id, "status": self.order_status}

    def cancel_order(self, order_id, symbol):
        self.cancelled_orders.append((order_id, symbol))
        return {"id": order_id, "status": "canceled"}

    def create_market_buy_order(self, symbol, cost):
        self.market_buys.append((symbol, cost))
        return {"id": "market-buy-1"}

    def create_market_sell_order(self, symbol, amount):
        self.market_sells.append((symbol, amount))
        return {"id": "market-sell-1"}

    def fetch_balance(self):
        return {"USD": {"free": 1000.0}}


def test_position_size_cost_matches_recorded_amount_value():
    helpers = load_trading_helpers()
    exchange = FakeExchange()

    amount, cost = helpers["get_position_size"](
        exchange,
        "ETH/USD",
        current_price=100.0,
        symbol_risk_slice=0.10,
        leverage=5,
    )

    assert amount == 5.0
    assert cost == 500.0
    assert amount * 100.0 == cost


def test_unfilled_limit_entry_is_cancelled_before_next_cycle():
    helpers = load_trading_helpers()
    exchange = FakeExchange(order_status="open")

    executed = helpers["place_entry_order"](
        exchange,
        "ETH/USD",
        "ETH",
        amount=1.25,
        cost=125.0,
        use_limit_orders=True,
        limit_order_offset_pct=0.001,
        enable_trading=True,
    )

    assert executed is False
    assert exchange.cancelled_orders == [("buy-1", "ETH/USD")]
    assert exchange.market_buys == []


def test_unfilled_limit_exit_is_cancelled_before_next_cycle():
    helpers = load_trading_helpers()
    exchange = FakeExchange(order_status="open")

    executed = helpers["place_exit_order"](
        exchange,
        "ETH/USD",
        "ETH",
        amount=1.25,
        reason="Profit-taking",
        use_limit_orders=True,
        limit_order_offset_pct=0.001,
        enable_trading=True,
    )

    assert executed is False
    assert exchange.cancelled_orders == [("sell-1", "ETH/USD")]
    assert exchange.market_sells == []


def test_limit_entry_status_error_does_not_fallback_with_open_order():
    helpers = load_trading_helpers()
    exchange = FakeExchange(fetch_order_error=RuntimeError("temporary status outage"))

    executed = helpers["place_entry_order"](
        exchange,
        "ETH/USD",
        "ETH",
        amount=1.25,
        cost=125.0,
        use_limit_orders=True,
        limit_order_offset_pct=0.001,
        enable_trading=True,
    )

    assert executed is False
    assert exchange.cancelled_orders == [("buy-1", "ETH/USD")]
    assert exchange.market_buys == []


def test_limit_exit_status_error_does_not_stack_market_sell():
    helpers = load_trading_helpers()
    exchange = FakeExchange(fetch_order_error=RuntimeError("temporary status outage"))

    executed = helpers["place_exit_order"](
        exchange,
        "ETH/USD",
        "ETH",
        amount=1.25,
        reason="Profit-taking",
        use_limit_orders=True,
        limit_order_offset_pct=0.001,
        enable_trading=True,
    )

    assert executed is False
    assert exchange.cancelled_orders == [("sell-1", "ETH/USD")]
    assert exchange.market_sells == []
