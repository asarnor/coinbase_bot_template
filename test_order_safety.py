#!/usr/bin/env python3
import ast
import types
import unittest
from pathlib import Path
from typing import Dict, Tuple
from unittest.mock import patch


FUNCTIONS_UNDER_TEST = {
    "reset_position_state",
    "extract_filled_amount",
    "cancel_limit_order",
    "apply_exit_fill",
    "place_entry_order",
    "place_exit_order",
    "get_position_size",
}


def load_order_helpers():
    source = Path("main_multi_symbol.py").read_text()
    tree = ast.parse(source)
    selected_nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS_UNDER_TEST
    ]
    module = ast.Module(body=selected_nodes, type_ignores=[])
    ast.fix_missing_locations(module)

    namespace = {
        "Dict": Dict,
        "Tuple": Tuple,
        "time": types.SimpleNamespace(sleep=lambda _seconds: None, time=lambda: 1234.0),
    }
    exec(compile(module, "main_multi_symbol.py", "exec"), namespace)
    return namespace


helpers = load_order_helpers()


class FakeExchange:
    def __init__(self, *, order_status=None, balance=None):
        self.order_status = order_status or {}
        self.balance = balance or {"USD": {"free": 0.0}}
        self.cancelled_orders = []
        self.market_buys = []
        self.market_sells = []
        self.limit_buys = []
        self.limit_sells = []

    def fetch_balance(self):
        return self.balance

    def fetch_ticker(self, _symbol):
        return {"last": 100.0}

    def create_limit_buy_order(self, symbol, amount, price):
        order = {"id": "limit-buy-1", "symbol": symbol, "amount": amount, "price": price}
        self.limit_buys.append(order)
        return order

    def create_limit_sell_order(self, symbol, amount, price):
        order = {"id": "limit-sell-1", "symbol": symbol, "amount": amount, "price": price}
        self.limit_sells.append(order)
        return order

    def fetch_order(self, _order_id, _symbol):
        return self.order_status

    def cancel_order(self, order_id, symbol):
        self.cancelled_orders.append((order_id, symbol))
        return {"id": order_id, "status": "canceled"}

    def create_market_buy_order(self, symbol, cost):
        self.market_buys.append((symbol, cost))
        return {"id": "market-buy-1", "filled": cost / 100.0}

    def create_market_sell_order(self, symbol, amount):
        self.market_sells.append((symbol, amount))
        return {"id": "market-sell-1", "filled": amount}


class OrderSafetyTest(unittest.TestCase):
    def test_position_size_cost_matches_recorded_amount(self):
        exchange = FakeExchange(balance={"USD": {"free": 1000.0}})

        amount, cost = helpers["get_position_size"](
            exchange,
            "ETH/USD",
            current_price=100.0,
            symbol_risk_slice=0.05,
            leverage=5,
        )

        self.assertEqual(amount, 2.5)
        self.assertEqual(cost, 250.0)
        self.assertEqual(amount * 100.0, cost)

    def test_open_entry_limit_is_cancelled_without_market_fallback(self):
        exchange = FakeExchange(
            order_status={"status": "open", "filled": 0.0, "amount": 2.5, "remaining": 2.5}
        )

        with patch("builtins.print"):
            executed, filled_amount = helpers["place_entry_order"](
                exchange,
                "ETH/USD",
                "ETH",
                amount=2.5,
                cost=250.0,
                use_limit_orders=True,
                limit_order_offset_pct=0.001,
                enable_trading=True,
            )

        self.assertFalse(executed)
        self.assertEqual(filled_amount, 0.0)
        self.assertEqual(exchange.cancelled_orders, [("limit-buy-1", "ETH/USD")])
        self.assertEqual(exchange.market_buys, [])

    def test_partial_entry_limit_returns_actual_fill_after_cancel(self):
        exchange = FakeExchange(
            order_status={"status": "open", "filled": 0.4, "amount": 2.5, "remaining": 2.1}
        )

        with patch("builtins.print"):
            executed, filled_amount = helpers["place_entry_order"](
                exchange,
                "ETH/USD",
                "ETH",
                amount=2.5,
                cost=250.0,
                use_limit_orders=True,
                limit_order_offset_pct=0.001,
                enable_trading=True,
            )

        self.assertTrue(executed)
        self.assertEqual(filled_amount, 0.4)
        self.assertEqual(exchange.cancelled_orders, [("limit-buy-1", "ETH/USD")])

    def test_open_exit_limit_is_cancelled_without_market_fallback(self):
        exchange = FakeExchange(
            order_status={"status": "open", "filled": 0.0, "amount": 1.0, "remaining": 1.0}
        )

        with patch("builtins.print"):
            executed, filled_amount = helpers["place_exit_order"](
                exchange,
                "ETH/USD",
                "ETH",
                amount=1.0,
                reason="Profit-taking",
                use_limit_orders=True,
                limit_order_offset_pct=0.001,
                enable_trading=True,
            )

        self.assertFalse(executed)
        self.assertEqual(filled_amount, 0.0)
        self.assertEqual(exchange.cancelled_orders, [("limit-sell-1", "ETH/USD")])
        self.assertEqual(exchange.market_sells, [])

    def test_partial_exit_reduces_position_without_resetting(self):
        position = {
            "in_position": True,
            "trailing_stop_price": 95.0,
            "position_amount": 1.0,
            "entry_price": 100.0,
            "peak_price": 110.0,
            "trailing_profit_target": 112.0,
            "breakeven_set": True,
            "last_exit_time": 0,
        }

        exit_amount, fully_exited = helpers["apply_exit_fill"](position, 0.4)

        self.assertEqual(exit_amount, 0.4)
        self.assertFalse(fully_exited)
        self.assertTrue(position["in_position"])
        self.assertEqual(position["position_amount"], 0.6)

    def test_full_exit_resets_position_and_records_cooldown(self):
        position = {
            "in_position": True,
            "trailing_stop_price": 95.0,
            "position_amount": 1.0,
            "entry_price": 100.0,
            "peak_price": 110.0,
            "trailing_profit_target": 112.0,
            "breakeven_set": True,
            "last_exit_time": 0,
        }

        exit_amount, fully_exited = helpers["apply_exit_fill"](position, 1.0)

        self.assertEqual(exit_amount, 1.0)
        self.assertTrue(fully_exited)
        self.assertFalse(position["in_position"])
        self.assertEqual(position["position_amount"], 0.0)
        self.assertEqual(position["last_exit_time"], 1234.0)


if __name__ == "__main__":
    unittest.main()
