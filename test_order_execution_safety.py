#!/usr/bin/env python3
"""Regression tests for live order safety helpers in main_multi_symbol.

The bot starts its infinite loop at import time, so these tests load only the
helper functions under test from the AST.
"""
import ast
import unittest
from pathlib import Path
from typing import Dict, Tuple

from risk_limits import extract_fill


class NoSleep:
    @staticmethod
    def sleep(_seconds):
        return None


def load_helpers():
    names = {
        "cancel_order_safely",
        "extract_reported_fill",
        "place_entry_order",
        "place_exit_order",
        "reset_position_state",
        "apply_exit_execution",
    }
    tree = ast.parse(Path("main_multi_symbol.py").read_text())
    selected = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    module = ast.Module(body=selected, type_ignores=[])
    namespace = {
        "Dict": Dict,
        "Tuple": Tuple,
        "extract_fill": extract_fill,
        "time": NoSleep,
    }
    exec(compile(ast.fix_missing_locations(module), "main_multi_symbol_helpers", "exec"), namespace)
    return namespace


HELPERS = load_helpers()
place_entry_order = HELPERS["place_entry_order"]
place_exit_order = HELPERS["place_exit_order"]
apply_exit_execution = HELPERS["apply_exit_execution"]


class FakeExchange:
    def __init__(self, order_status=None, fetch_order_error=None):
        self.order_status = order_status or {"status": "open", "filled": 0}
        self.fetch_order_error = fetch_order_error
        self.canceled = []
        self.market_buys = []
        self.market_sells = []

    def fetch_ticker(self, _symbol):
        return {"last": 100.0}

    def create_limit_buy_order(self, _symbol, _amount, _price):
        return {"id": "limit-buy-1"}

    def create_limit_sell_order(self, _symbol, _amount, _price):
        return {"id": "limit-sell-1"}

    def fetch_order(self, _order_id, _symbol):
        if self.fetch_order_error:
            raise self.fetch_order_error
        return dict(self.order_status)

    def cancel_order(self, order_id, symbol):
        self.canceled.append((order_id, symbol))
        return {"id": order_id, "status": "canceled"}

    def create_market_buy_order(self, symbol, cost):
        self.market_buys.append((symbol, cost))
        return {"id": "market-buy-1", "filled": cost / 100.0, "average": 100.0}

    def create_market_sell_order(self, symbol, amount):
        self.market_sells.append((symbol, amount))
        return {"id": "market-sell-1", "filled": amount, "average": 99.0}

    def fetch_balance(self):
        return {"BTC": {"free": 1.0}}

    def amount_to_precision(self, _symbol, amount):
        return str(amount)


class LimitEntrySafetyTests(unittest.TestCase):
    def test_unfilled_limit_entry_is_canceled_without_market_fallback(self):
        exchange = FakeExchange({"status": "open", "filled": 0, "amount": 1.0})

        executed, filled, average = place_entry_order(
            exchange, "BTC/USD", "BTC", 1.0, 100.0, True, 0.001, True
        )

        self.assertFalse(executed)
        self.assertEqual(filled, 0.0)
        self.assertEqual(average, 0.0)
        self.assertEqual(exchange.canceled, [("limit-buy-1", "BTC/USD")])
        self.assertEqual(exchange.market_buys, [])

    def test_uncertain_limit_entry_is_canceled_without_market_fallback(self):
        exchange = FakeExchange(fetch_order_error=RuntimeError("temporary exchange error"))

        executed, filled, average = place_entry_order(
            exchange, "BTC/USD", "BTC", 1.0, 100.0, True, 0.001, True
        )

        self.assertFalse(executed)
        self.assertEqual(filled, 0.0)
        self.assertEqual(average, 0.0)
        self.assertEqual(exchange.canceled, [("limit-buy-1", "BTC/USD")])
        self.assertEqual(exchange.market_buys, [])

    def test_partial_limit_entry_records_confirmed_fill(self):
        exchange = FakeExchange({"status": "open", "filled": 0.25, "average": 99.5})

        executed, filled, average = place_entry_order(
            exchange, "BTC/USD", "BTC", 1.0, 100.0, True, 0.001, True
        )

        self.assertTrue(executed)
        self.assertAlmostEqual(filled, 0.25)
        self.assertAlmostEqual(average, 99.5)
        self.assertEqual(exchange.canceled, [("limit-buy-1", "BTC/USD")])


class LimitExitSafetyTests(unittest.TestCase):
    def test_unfilled_limit_exit_is_canceled_without_market_fallback(self):
        exchange = FakeExchange({"status": "open", "filled": 0, "amount": 1.0})

        executed, filled, average = place_exit_order(
            exchange, "BTC/USD", "BTC", 1.0, "Profit-taking", True, 0.001, True
        )

        self.assertFalse(executed)
        self.assertEqual(filled, 0.0)
        self.assertEqual(average, 0.0)
        self.assertEqual(exchange.canceled, [("limit-sell-1", "BTC/USD")])
        self.assertEqual(exchange.market_sells, [])

    def test_partial_limit_exit_returns_confirmed_fill(self):
        exchange = FakeExchange({"status": "open", "filled": 0.4, "average": 101.0})

        executed, filled, average = place_exit_order(
            exchange, "BTC/USD", "BTC", 1.0, "Profit-taking", True, 0.001, True
        )

        self.assertTrue(executed)
        self.assertAlmostEqual(filled, 0.4)
        self.assertAlmostEqual(average, 101.0)
        self.assertEqual(exchange.canceled, [("limit-sell-1", "BTC/USD")])

    def test_partial_exit_reduces_position_instead_of_resetting(self):
        position = {
            "in_position": True,
            "position_amount": 1.0,
            "last_exit_time": 0,
            "trailing_stop_price": 90.0,
            "entry_price": 100.0,
            "peak_price": 110.0,
            "trailing_profit_target": 108.0,
            "breakeven_set": True,
        }

        fully_exited, effective_amount = apply_exit_execution(position, 0.4)

        self.assertFalse(fully_exited)
        self.assertAlmostEqual(effective_amount, 0.4)
        self.assertTrue(position["in_position"])
        self.assertAlmostEqual(position["position_amount"], 0.6)


if __name__ == "__main__":
    unittest.main()
