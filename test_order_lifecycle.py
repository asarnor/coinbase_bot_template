#!/usr/bin/env python3
"""Focused tests for limit order lifecycle helpers."""
import ast
import unittest


def load_order_helpers():
    with open("main_multi_symbol.py", "r", encoding="utf-8") as handle:
        module = ast.parse(handle.read())

    wanted = {
        "OrderResult",
        "CancelResult",
        "clear_pending_entry",
        "clear_pending_exit",
        "order_filled_amount",
        "order_average_price",
        "cancel_limit_order",
        "place_entry_order",
        "place_exit_order",
        "reconcile_pending_orders",
    }
    selected_nodes = [
        node
        for node in module.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in wanted
    ]
    helper_module = ast.Module(body=selected_nodes, type_ignores=[])
    ast.fix_missing_locations(helper_module)

    namespace = {}
    exec("from typing import Dict, NamedTuple, Optional\nimport time\n", namespace)
    exec(compile(helper_module, "main_multi_symbol.py", "exec"), namespace)
    return namespace


helpers = load_order_helpers()
OrderResult = helpers["OrderResult"]
place_entry_order = helpers["place_entry_order"]
place_exit_order = helpers["place_exit_order"]
reconcile_pending_orders = helpers["reconcile_pending_orders"]


class FakeExchange:
    def __init__(self, fetch_order_statuses):
        self.fetch_order_statuses = list(fetch_order_statuses)
        self.created_limit_buys = []
        self.created_limit_sells = []
        self.created_market_buys = []
        self.created_market_sells = []
        self.canceled_orders = []
        self.fail_fetch_order = False

    def fetch_ticker(self, symbol):
        return {"last": 100.0}

    def create_limit_buy_order(self, symbol, amount, price):
        self.created_limit_buys.append((symbol, amount, price))
        return {"id": "buy-1"}

    def create_limit_sell_order(self, symbol, amount, price):
        self.created_limit_sells.append((symbol, amount, price))
        return {"id": "sell-1"}

    def fetch_order(self, order_id, symbol):
        if self.fail_fetch_order:
            raise RuntimeError("fetch failed")
        return self.fetch_order_statuses.pop(0)

    def cancel_order(self, order_id, symbol):
        self.canceled_orders.append((order_id, symbol))

    def create_market_sell_order(self, symbol, amount):
        self.created_market_sells.append((symbol, amount))
        return {"id": "market-sell-1"}

    def create_market_buy_order(self, symbol, cost):
        self.created_market_buys.append((symbol, cost))
        return {"id": "market-buy-1"}


class OrderLifecycleTest(unittest.TestCase):
    def test_unfilled_limit_entry_is_canceled_and_not_reported_executed(self):
        exchange = FakeExchange([
            {"status": "open", "filled": 0},
            {"status": "canceled", "filled": 0},
        ])

        result = place_entry_order(exchange, "ETH/USD", "ETH", 2.0, 200.0, True, 0.01, True)

        self.assertEqual(result, OrderResult(False, 0.0, "buy-1", True, False))
        self.assertEqual(exchange.canceled_orders, [("buy-1", "ETH/USD")])

    def test_unfilled_limit_exit_is_canceled_then_sold_at_market_once(self):
        exchange = FakeExchange([
            {"status": "open", "filled": 0},
            {"status": "canceled", "filled": 0},
        ])

        result = place_exit_order(exchange, "ETH/USD", "ETH", 2.0, "Profit-taking", True, 0.01, True)

        self.assertEqual(result, OrderResult(True, 2.0, "market-sell-1", True, False))
        self.assertEqual(exchange.canceled_orders, [("sell-1", "ETH/USD")])
        self.assertEqual(exchange.created_market_sells, [("ETH/USD", 2.0)])

    def test_partially_filled_limit_exit_sells_only_remaining_amount(self):
        exchange = FakeExchange([
            {"status": "open", "filled": 0.5},
            {"status": "canceled", "filled": 0.5},
        ])

        result = place_exit_order(exchange, "ETH/USD", "ETH", 2.0, "Profit-taking", True, 0.01, True)

        self.assertEqual(result, OrderResult(True, 2.0, "market-sell-1", True, False))
        self.assertEqual(exchange.created_market_sells, [("ETH/USD", 1.5)])

    def test_unconfirmed_limit_exit_cancel_does_not_place_overlapping_market_sell(self):
        exchange = FakeExchange([
            {"status": "open", "filled": 0},
            {"status": "open", "filled": 0},
        ])

        result = place_exit_order(exchange, "ETH/USD", "ETH", 2.0, "Profit-taking", True, 0.01, True)

        self.assertEqual(result, OrderResult(False, 0.0, "sell-1", False, True))
        self.assertEqual(exchange.canceled_orders, [("sell-1", "ETH/USD")])
        self.assertEqual(exchange.created_market_sells, [])

    def test_limit_entry_fetch_failure_does_not_fallback_to_second_buy(self):
        exchange = FakeExchange([])
        exchange.fail_fetch_order = True

        result = place_entry_order(exchange, "ETH/USD", "ETH", 2.0, 200.0, True, 0.01, True)

        self.assertEqual(result, OrderResult(False, 0.0, "buy-1", False, True))
        self.assertEqual(exchange.created_market_buys, [])

    def test_pending_entry_blocks_new_entry_until_resolved(self):
        exchange = FakeExchange([{"status": "open", "filled": 0}])
        position = {
            "in_position": False,
            "trailing_stop_price": 0.0,
            "position_amount": 0.0,
            "entry_price": 0.0,
            "peak_price": 0.0,
            "trailing_profit_target": 0.0,
            "breakeven_set": False,
            "pending_entry_order_id": "buy-1",
            "pending_entry_amount": 2.0,
            "pending_entry_price": 99.0,
            "pending_exit_order_id": None,
        }

        blocked = reconcile_pending_orders(exchange, "ETH/USD", "ETH", position, 100.0, 2.0, 0.03, 1.5)

        self.assertTrue(blocked)
        self.assertFalse(position["in_position"])
        self.assertEqual(position["pending_entry_order_id"], "buy-1")


if __name__ == "__main__":
    unittest.main()
