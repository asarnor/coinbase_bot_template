#!/usr/bin/env python3
import ast
import pathlib
import types
import unittest
from typing import Any, Dict, List, Tuple


FUNCTIONS_UNDER_TEST = {
    "order_float",
    "order_id",
    "entry_result",
    "entry_result_from_order",
    "cancel_order_safely",
    "place_entry_order",
    "place_exit_order",
    "get_position_size",
    "configure_effective_leverage",
}


def load_functions():
    source_path = pathlib.Path(__file__).with_name("main_multi_symbol.py")
    tree = ast.parse(source_path.read_text())
    function_nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS_UNDER_TEST
    ]
    module = ast.Module(body=function_nodes, type_ignores=[])
    ast.fix_missing_locations(module)

    namespace = {
        "Any": Any,
        "Dict": Dict,
        "List": List,
        "Tuple": Tuple,
        "TradingJournal": object,
        "time": types.SimpleNamespace(sleep=lambda _: None),
        "print": lambda *args, **kwargs: None,
    }
    exec(compile(module, str(source_path), "exec"), namespace)
    return namespace


class FakeJournal:
    def __init__(self):
        self.events = []

    def log_event(self, *args, **kwargs):
        self.events.append((args, kwargs))


class BalanceExchange:
    def __init__(self, free_usd=1000.0, leverage_error=None):
        self.free_usd = free_usd
        self.leverage_error = leverage_error
        self.leverage_calls = []

    def fetch_balance(self):
        return {"USD": {"free": self.free_usd}}

    def set_leverage(self, leverage, symbol):
        self.leverage_calls.append((leverage, symbol))
        if self.leverage_error:
            raise self.leverage_error


class EntryExchange:
    def __init__(self, market_order=None, limit_status=None):
        self.market_order = market_order or {"id": "market-1", "filled": 1.75, "average": 114.285714, "cost": 200.0}
        self.limit_status = limit_status or {"id": "limit-1", "status": "open"}
        self.canceled = []

    def fetch_ticker(self, symbol):
        return {"last": 100.0}

    def create_market_buy_order(self, symbol, cost):
        return self.market_order

    def create_limit_buy_order(self, symbol, amount, price):
        return {"id": "limit-1"}

    def fetch_order(self, order_id, symbol):
        return self.limit_status

    def cancel_order(self, order_id, symbol):
        self.canceled.append((order_id, symbol))


class ExitExchange:
    def __init__(self, status=None):
        self.status = status or {"id": "exit-1", "status": "open"}
        self.canceled = []
        self.market_sells = []

    def fetch_ticker(self, symbol):
        return {"last": 100.0}

    def create_limit_sell_order(self, symbol, amount, price):
        return {"id": "exit-1"}

    def fetch_order(self, order_id, symbol):
        return self.status

    def cancel_order(self, order_id, symbol):
        self.canceled.append((order_id, symbol))

    def create_market_sell_order(self, symbol, amount):
        self.market_sells.append((symbol, amount))
        return {"id": "market-sell-1"}


class OrderExecutionSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.functions = load_functions()

    def test_failed_leverage_configuration_forces_unleveraged_sizing(self):
        configure_effective_leverage = self.functions["configure_effective_leverage"]
        get_position_size = self.functions["get_position_size"]
        exchange = BalanceExchange(leverage_error=RuntimeError("not supported"))
        journal = FakeJournal()

        effective_leverage = configure_effective_leverage(exchange, ["ETH/USD"], 5, journal)
        amount, cost = get_position_size(exchange, "ETH/USD", 100.0, 0.20, effective_leverage)

        self.assertEqual(effective_leverage, 1)
        self.assertEqual(cost, 200.0)
        self.assertEqual(amount, 2.0)
        self.assertEqual(len(journal.events), 1)

    def test_successful_leverage_configuration_keeps_consistent_notional(self):
        configure_effective_leverage = self.functions["configure_effective_leverage"]
        get_position_size = self.functions["get_position_size"]
        exchange = BalanceExchange()

        effective_leverage = configure_effective_leverage(exchange, ["ETH/USD", "BTC/USD"], 5, FakeJournal())
        amount, cost = get_position_size(exchange, "ETH/USD", 100.0, 0.20, effective_leverage)

        self.assertEqual(effective_leverage, 5)
        self.assertEqual(cost, 1000.0)
        self.assertEqual(amount, 10.0)
        self.assertEqual(exchange.leverage_calls, [(5, "ETH/USD"), (5, "BTC/USD")])

    def test_entry_result_uses_actual_filled_amount_for_position_state(self):
        entry_result_from_order = self.functions["entry_result_from_order"]

        result = entry_result_from_order(
            {"id": "order-1", "filled": "1.9", "average": "105", "cost": "199.5"},
            fallback_amount=2.0,
            fallback_price=100.0,
            fallback_cost=200.0,
        )

        self.assertTrue(result["executed"])
        self.assertEqual(result["filled_amount"], 1.9)
        self.assertEqual(result["average_price"], 105.0)
        self.assertEqual(result["cost_usd"], 199.5)
        self.assertEqual(result["order_id"], "order-1")

    def test_market_entry_returns_actual_fill_details(self):
        place_entry_order = self.functions["place_entry_order"]
        exchange = EntryExchange()

        result = place_entry_order(
            exchange,
            "ETH/USD",
            "ETH",
            2.0,
            200.0,
            100.0,
            False,
            0.001,
            True,
        )

        self.assertTrue(result["executed"])
        self.assertEqual(result["filled_amount"], 1.75)
        self.assertAlmostEqual(result["average_price"], 114.285714)
        self.assertEqual(result["cost_usd"], 200.0)
        self.assertEqual(result["order_id"], "market-1")

    def test_unfilled_limit_entry_is_canceled_before_retrying_later(self):
        place_entry_order = self.functions["place_entry_order"]
        exchange = EntryExchange(limit_status={"id": "limit-1", "status": "open"})

        result = place_entry_order(
            exchange,
            "ETH/USD",
            "ETH",
            2.0,
            200.0,
            100.0,
            True,
            0.001,
            True,
        )

        self.assertFalse(result["executed"])
        self.assertTrue(result["pending"])
        self.assertEqual(exchange.canceled, [("limit-1", "ETH/USD")])

    def test_unfilled_limit_exit_is_canceled_without_market_fallback(self):
        place_exit_order = self.functions["place_exit_order"]
        exchange = ExitExchange(status={"id": "exit-1", "status": "open"})

        executed = place_exit_order(
            exchange,
            "ETH/USD",
            "ETH",
            2.0,
            "Profit-taking",
            True,
            0.001,
            True,
        )

        self.assertFalse(executed)
        self.assertEqual(exchange.canceled, [("exit-1", "ETH/USD")])
        self.assertEqual(exchange.market_sells, [])


if __name__ == "__main__":
    unittest.main()
