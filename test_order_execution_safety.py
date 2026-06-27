#!/usr/bin/env python3
import ast
import pathlib
import types
import unittest
from typing import Dict, List, Tuple


MODULE_PATH = pathlib.Path(__file__).with_name("main_multi_symbol.py")


def load_bot_functions(*function_names):
    module_ast = ast.parse(MODULE_PATH.read_text())
    selected_nodes = [
        node
        for node in module_ast.body
        if isinstance(node, ast.FunctionDef) and node.name in function_names
    ]
    test_module = ast.Module(body=selected_nodes, type_ignores=[])
    ast.fix_missing_locations(test_module)

    namespace = {
        "Dict": Dict,
        "List": List,
        "Tuple": Tuple,
        "time": types.SimpleNamespace(sleep=lambda seconds: None, time=lambda: 12345.0),
    }
    exec(compile(test_module, str(MODULE_PATH), "exec"), namespace)
    return namespace


FUNCTIONS = load_bot_functions(
    "positive_float",
    "get_order_filled_amount",
    "get_order_cost",
    "cancel_open_order",
    "reset_position_state",
    "apply_exit_fill",
    "place_entry_order",
    "place_exit_order",
    "get_position_size",
    "configure_effective_leverage",
)


class FakeExchange:
    def __init__(self):
        self.ticker_price = 100.0
        self.next_order = {"id": "order-1"}
        self.next_status = {"status": "open", "filled": 0.0, "amount": 1.0}
        self.fetch_order_error = None
        self.limit_buys = []
        self.market_buys = []
        self.limit_sells = []
        self.market_sells = []
        self.canceled = []
        self.balance = {"USD": {"free": 1000.0}}
        self.leverage_error = None
        self.leverage_calls = []

    def fetch_ticker(self, symbol):
        return {"last": self.ticker_price}

    def create_limit_buy_order(self, symbol, amount, price):
        self.limit_buys.append((symbol, amount, price))
        return dict(self.next_order)

    def create_market_buy_order(self, symbol, cost):
        self.market_buys.append((symbol, cost))
        return {"id": "market-buy", "filled": cost / self.ticker_price, "cost": cost}

    def create_limit_sell_order(self, symbol, amount, price):
        self.limit_sells.append((symbol, amount, price))
        return dict(self.next_order)

    def create_market_sell_order(self, symbol, amount):
        self.market_sells.append((symbol, amount))
        return {"id": "market-sell", "filled": amount}

    def fetch_order(self, order_id, symbol):
        if self.fetch_order_error is not None:
            raise self.fetch_order_error
        return dict(self.next_status)

    def cancel_order(self, order_id, symbol):
        self.canceled.append((order_id, symbol))

    def fetch_balance(self):
        return self.balance

    def set_leverage(self, leverage, symbol):
        self.leverage_calls.append((leverage, symbol))
        if self.leverage_error is not None:
            raise self.leverage_error


class OrderExecutionSafetyTests(unittest.TestCase):
    def test_unfilled_limit_entry_is_canceled_without_market_fallback(self):
        exchange = FakeExchange()

        result = FUNCTIONS["place_entry_order"](
            exchange, "ETH/USD", "ETH", 1.0, 100.0, True, 0.001, True
        )

        self.assertEqual(result, (False, 0.0, 0.0))
        self.assertEqual(exchange.canceled, [("order-1", "ETH/USD")])
        self.assertEqual(exchange.market_buys, [])

    def test_uncertain_limit_entry_is_canceled_without_market_fallback(self):
        exchange = FakeExchange()
        exchange.fetch_order_error = RuntimeError("timeout")

        result = FUNCTIONS["place_entry_order"](
            exchange, "ETH/USD", "ETH", 1.0, 100.0, True, 0.001, True
        )

        self.assertEqual(result, (False, 0.0, 0.0))
        self.assertEqual(exchange.canceled, [("order-1", "ETH/USD")])
        self.assertEqual(exchange.market_buys, [])

    def test_partially_filled_limit_entry_tracks_confirmed_fill(self):
        exchange = FakeExchange()
        exchange.next_status = {"status": "open", "filled": 0.25, "cost": 25.0, "amount": 1.0}

        result = FUNCTIONS["place_entry_order"](
            exchange, "ETH/USD", "ETH", 1.0, 100.0, True, 0.001, True
        )

        self.assertEqual(result, (True, 0.25, 25.0))
        self.assertEqual(exchange.canceled, [("order-1", "ETH/USD")])

    def test_unfilled_limit_exit_is_canceled_without_market_fallback(self):
        exchange = FakeExchange()

        result = FUNCTIONS["place_exit_order"](
            exchange, "ETH/USD", "ETH", 1.0, "Profit-taking", True, 0.001, True
        )

        self.assertEqual(result, (False, 0.0))
        self.assertEqual(exchange.canceled, [("order-1", "ETH/USD")])
        self.assertEqual(exchange.market_sells, [])

    def test_partial_exit_fill_reduces_local_position(self):
        position = {
            "in_position": True,
            "position_amount": 1.0,
            "trailing_stop_price": 90.0,
            "entry_price": 100.0,
            "peak_price": 110.0,
            "trailing_profit_target": 120.0,
            "breakeven_set": True,
            "last_exit_time": 0,
        }

        self.assertTrue(FUNCTIONS["apply_exit_fill"](position, 0.4))

        self.assertTrue(position["in_position"])
        self.assertAlmostEqual(position["position_amount"], 0.6)

    def test_leverage_failure_uses_one_x_effective_leverage(self):
        exchange = FakeExchange()
        exchange.leverage_error = RuntimeError("not supported")

        effective_leverage = FUNCTIONS["configure_effective_leverage"](
            exchange, ["ETH/USD", "BTC/USD"], 5
        )
        amount, cost = FUNCTIONS["get_position_size"](exchange, "ETH/USD", 100.0, 0.2, effective_leverage)

        self.assertEqual(effective_leverage, 1)
        self.assertEqual(amount, 2.0)
        self.assertEqual(cost, 200.0)


if __name__ == "__main__":
    unittest.main()
