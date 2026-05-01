#!/usr/bin/env python3
import ast
import types
import unittest
from pathlib import Path


def load_order_functions():
    source = Path("main_multi_symbol.py").read_text(encoding="utf-8")
    tree = ast.parse(source, filename="main_multi_symbol.py")
    wanted = {
        "is_order_filled",
        "handle_unfilled_limit_order",
        "place_entry_order",
        "place_exit_order",
    }
    module = ast.Module(
        body=[node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted],
        type_ignores=[],
    )
    ast.fix_missing_locations(module)
    namespace = {"time": types.SimpleNamespace(sleep=lambda _seconds: None)}
    exec(compile(module, "main_multi_symbol.py", "exec"), namespace)
    return namespace


ORDER_FUNCTIONS = load_order_functions()


class FakeExchange:
    def __init__(self, statuses, cancel_raises=False, fetch_order_raises=False):
        self.statuses = list(statuses)
        self.cancel_raises = cancel_raises
        self.fetch_order_raises = fetch_order_raises
        self.canceled = []
        self.limit_buys = []
        self.limit_sells = []
        self.market_buys = []
        self.market_sells = []

    def fetch_ticker(self, symbol):
        return {"last": 100.0}

    def create_limit_buy_order(self, symbol, amount, price):
        self.limit_buys.append((symbol, amount, price))
        return {"id": "buy-1"}

    def create_limit_sell_order(self, symbol, amount, price):
        self.limit_sells.append((symbol, amount, price))
        return {"id": "sell-1"}

    def fetch_order(self, order_id, symbol):
        if self.fetch_order_raises:
            raise RuntimeError("status unavailable")
        return {"id": order_id, "status": self.statuses.pop(0)}

    def cancel_order(self, order_id, symbol):
        self.canceled.append((order_id, symbol))
        if self.cancel_raises:
            raise RuntimeError("already closed")
        return {"id": order_id, "status": "canceled"}

    def create_market_buy_order(self, symbol, cost):
        self.market_buys.append((symbol, cost))
        return {"id": "market-buy-1"}

    def create_market_sell_order(self, symbol, amount):
        self.market_sells.append((symbol, amount))
        return {"id": "market-sell-1"}


class LimitOrderTests(unittest.TestCase):
    def test_unfilled_entry_limit_is_canceled_and_not_treated_as_filled(self):
        exchange = FakeExchange(statuses=["open"])

        result = ORDER_FUNCTIONS["place_entry_order"](
            exchange,
            "ETH/USD",
            "ETH",
            0.25,
            25.0,
            True,
            0.001,
            True,
        )

        self.assertFalse(result)
        self.assertEqual(exchange.canceled, [("buy-1", "ETH/USD")])
        self.assertEqual(exchange.market_buys, [])

    def test_entry_limit_filled_before_cancel_is_treated_as_filled(self):
        exchange = FakeExchange(statuses=["open", "closed"], cancel_raises=True)

        result = ORDER_FUNCTIONS["place_entry_order"](
            exchange,
            "ETH/USD",
            "ETH",
            0.25,
            25.0,
            True,
            0.001,
            True,
        )

        self.assertTrue(result)
        self.assertEqual(exchange.canceled, [("buy-1", "ETH/USD")])

    def test_entry_limit_status_error_cancels_without_market_fallback(self):
        exchange = FakeExchange(statuses=[], fetch_order_raises=True)

        result = ORDER_FUNCTIONS["place_entry_order"](
            exchange,
            "ETH/USD",
            "ETH",
            0.25,
            25.0,
            True,
            0.001,
            True,
        )

        self.assertFalse(result)
        self.assertEqual(exchange.canceled, [("buy-1", "ETH/USD")])
        self.assertEqual(exchange.market_buys, [])

    def test_unfilled_exit_limit_is_canceled_and_position_remains_active(self):
        exchange = FakeExchange(statuses=["open"])

        result = ORDER_FUNCTIONS["place_exit_order"](
            exchange,
            "ETH/USD",
            "ETH",
            0.25,
            "Profit-taking",
            True,
            0.001,
            True,
        )

        self.assertFalse(result)
        self.assertEqual(exchange.canceled, [("sell-1", "ETH/USD")])
        self.assertEqual(exchange.market_sells, [])


if __name__ == "__main__":
    unittest.main()
