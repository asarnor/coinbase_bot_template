#!/usr/bin/env python3
import ast
import pathlib
import types
import unittest
from typing import Dict, List, Tuple


MODULE_PATH = pathlib.Path(__file__).with_name("main_multi_symbol.py")
FUNCTION_NAMES = {
    "cancel_unfilled_limit_order",
    "place_entry_order",
    "place_exit_order",
    "get_position_size",
}


def load_trading_helpers():
    tree = ast.parse(MODULE_PATH.read_text())
    selected = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in FUNCTION_NAMES
    ]
    module = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(module)

    namespace = {
        "Dict": Dict,
        "List": List,
        "Tuple": Tuple,
        "time": types.SimpleNamespace(sleep=lambda _seconds: None),
    }
    exec(compile(module, str(MODULE_PATH), "exec"), namespace)
    return namespace


HELPERS = load_trading_helpers()


class FakeExchange:
    def __init__(self, order_status=None, fetch_order_error=None):
        self.order_status = order_status or {"status": "open"}
        self.fetch_order_error = fetch_order_error
        self.cancelled_orders = []
        self.market_buys = []
        self.market_sells = []

    def fetch_ticker(self, symbol):
        return {"last": 100.0}

    def create_limit_buy_order(self, symbol, amount, price):
        return {"id": "entry-1"}

    def create_limit_sell_order(self, symbol, amount, price):
        return {"id": "exit-1"}

    def fetch_order(self, order_id, symbol):
        if self.fetch_order_error:
            raise self.fetch_order_error
        return self.order_status

    def cancel_order(self, order_id, symbol):
        self.cancelled_orders.append((order_id, symbol))

    def create_market_buy_order(self, symbol, cost):
        self.market_buys.append((symbol, cost))
        return {"id": "market-buy-1"}

    def create_market_sell_order(self, symbol, amount):
        self.market_sells.append((symbol, amount))
        return {"id": "market-sell-1"}


class BalanceExchange:
    def fetch_balance(self):
        return {"USD": {"free": 1000.0}}


class OrderSafetyTests(unittest.TestCase):
    def test_unfilled_limit_entry_is_cancelled_without_market_fallback(self):
        exchange = FakeExchange(order_status={"status": "open"})

        executed = HELPERS["place_entry_order"](
            exchange,
            "ETH/USD",
            "ETH",
            1.0,
            100.0,
            True,
            0.001,
            True,
        )

        self.assertFalse(executed)
        self.assertEqual(exchange.cancelled_orders, [("entry-1", "ETH/USD")])
        self.assertEqual(exchange.market_buys, [])

    def test_unverified_limit_entry_is_cancelled_without_market_fallback(self):
        exchange = FakeExchange(fetch_order_error=RuntimeError("temporary exchange error"))

        executed = HELPERS["place_entry_order"](
            exchange,
            "ETH/USD",
            "ETH",
            1.0,
            100.0,
            True,
            0.001,
            True,
        )

        self.assertFalse(executed)
        self.assertEqual(exchange.cancelled_orders, [("entry-1", "ETH/USD")])
        self.assertEqual(exchange.market_buys, [])

    def test_unfilled_limit_exit_is_cancelled_without_market_fallback(self):
        exchange = FakeExchange(order_status={"status": "open"})

        executed = HELPERS["place_exit_order"](
            exchange,
            "ETH/USD",
            "ETH",
            1.0,
            "Profit-taking",
            True,
            0.001,
            True,
        )

        self.assertFalse(executed)
        self.assertEqual(exchange.cancelled_orders, [("exit-1", "ETH/USD")])
        self.assertEqual(exchange.market_sells, [])

    def test_position_size_cost_matches_recorded_base_amount(self):
        amount, cost = HELPERS["get_position_size"](
            BalanceExchange(),
            "ETH/USD",
            100.0,
            0.20,
            5,
        )

        self.assertEqual(amount, 10.0)
        self.assertEqual(cost, 1000.0)
        self.assertEqual(amount * 100.0, cost)


if __name__ == "__main__":
    unittest.main()
