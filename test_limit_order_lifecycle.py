import ast
import pathlib
import types
import unittest
from typing import Dict


def load_order_helpers():
    source = pathlib.Path(__file__).with_name("main_multi_symbol.py").read_text()
    module_ast = ast.parse(source)
    wanted = {
        "is_order_closed",
        "cancel_unfilled_limit_order",
        "place_entry_order",
        "place_exit_order",
    }
    helper_defs = [
        node
        for node in module_ast.body
        if isinstance(node, ast.FunctionDef) and node.name in wanted
    ]
    namespace = {"Dict": Dict, "time": types.SimpleNamespace(sleep=lambda seconds: None)}
    compiled = compile(ast.Module(body=helper_defs, type_ignores=[]), filename="main_multi_symbol.py", mode="exec")
    exec(compiled, namespace)
    return namespace


HELPERS = load_order_helpers()
place_entry_order = HELPERS["place_entry_order"]
place_exit_order = HELPERS["place_exit_order"]


class FakeExchange:
    def __init__(self, status=None, fetch_order_exc=None, create_limit_exc=None):
        self.status = status or {"status": "open"}
        self.fetch_order_exc = fetch_order_exc
        self.create_limit_exc = create_limit_exc
        self.canceled_orders = []
        self.market_buys = []
        self.market_sells = []

    def fetch_ticker(self, symbol):
        return {"last": 100.0}

    def create_limit_buy_order(self, symbol, amount, limit_price):
        if self.create_limit_exc:
            raise self.create_limit_exc
        return {"id": "limit-buy-1"}

    def create_limit_sell_order(self, symbol, amount, limit_price):
        if self.create_limit_exc:
            raise self.create_limit_exc
        return {"id": "limit-sell-1"}

    def fetch_order(self, order_id, symbol):
        if self.fetch_order_exc:
            raise self.fetch_order_exc
        return self.status

    def cancel_order(self, order_id, symbol):
        self.canceled_orders.append((order_id, symbol))
        return {"id": order_id, "status": "canceled"}

    def create_market_buy_order(self, symbol, cost):
        self.market_buys.append((symbol, cost))
        return {"id": "market-buy-1"}

    def create_market_sell_order(self, symbol, amount):
        self.market_sells.append((symbol, amount))
        return {"id": "market-sell-1"}


class LimitOrderLifecycleTests(unittest.TestCase):
    def test_unfilled_limit_entry_is_canceled_without_market_fallback(self):
        exchange = FakeExchange(status={"status": "open"})

        executed = place_entry_order(
            exchange,
            "ETH/USD",
            "ETH",
            amount=0.5,
            cost=50.0,
            use_limit_orders=True,
            limit_order_offset_pct=0.001,
            enable_trading=True,
        )

        self.assertFalse(executed)
        self.assertEqual(exchange.canceled_orders, [("limit-buy-1", "ETH/USD")])
        self.assertEqual(exchange.market_buys, [])

    def test_unfilled_limit_exit_is_canceled_without_market_fallback(self):
        exchange = FakeExchange(status={"status": "open"})

        executed = place_exit_order(
            exchange,
            "ETH/USD",
            "ETH",
            amount=0.5,
            reason="Profit-taking",
            use_limit_orders=True,
            limit_order_offset_pct=0.001,
            enable_trading=True,
        )

        self.assertFalse(executed)
        self.assertEqual(exchange.canceled_orders, [("limit-sell-1", "ETH/USD")])
        self.assertEqual(exchange.market_sells, [])

    def test_limit_entry_status_failure_cancels_known_order_without_market_fallback(self):
        exchange = FakeExchange(fetch_order_exc=RuntimeError("network timeout"))

        executed = place_entry_order(
            exchange,
            "ETH/USD",
            "ETH",
            amount=0.5,
            cost=50.0,
            use_limit_orders=True,
            limit_order_offset_pct=0.001,
            enable_trading=True,
        )

        self.assertFalse(executed)
        self.assertEqual(exchange.canceled_orders, [("limit-buy-1", "ETH/USD")])
        self.assertEqual(exchange.market_buys, [])

    def test_limit_exit_creation_failure_does_not_submit_market_sell(self):
        exchange = FakeExchange(create_limit_exc=RuntimeError("exchange rejected order"))

        executed = place_exit_order(
            exchange,
            "ETH/USD",
            "ETH",
            amount=0.5,
            reason="Profit-taking",
            use_limit_orders=True,
            limit_order_offset_pct=0.001,
            enable_trading=True,
        )

        self.assertFalse(executed)
        self.assertEqual(exchange.canceled_orders, [])
        self.assertEqual(exchange.market_sells, [])


if __name__ == "__main__":
    unittest.main()
