#!/usr/bin/env python3
import ast
import types
import unittest
from pathlib import Path
from typing import Dict, List, Tuple


ROOT = Path(__file__).resolve().parent


def load_function(module_path: str, function_name: str):
    source = (ROOT / module_path).read_text()
    tree = ast.parse(source, filename=module_path)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            compiled = compile(ast.Module(body=[node], type_ignores=[]), module_path, "exec")
            scope = {
                "Dict": Dict,
                "List": List,
                "Tuple": Tuple,
                "time": types.SimpleNamespace(sleep=lambda _seconds: None),
            }
            exec(compiled, scope)
            return scope[function_name]
    raise AssertionError(f"{function_name} not found in {module_path}")


class BalanceExchange:
    def __init__(self, free_usd: float):
        self.free_usd = free_usd

    def fetch_balance(self):
        return {"USD": {"free": self.free_usd}}


class LimitOrderExchange:
    def __init__(self, status="open", fetch_raises=False, limit_buy_raises=False):
        self.status = status
        self.fetch_raises = fetch_raises
        self.limit_buy_raises = limit_buy_raises
        self.limit_buys = []
        self.limit_sells = []
        self.market_buys = []
        self.market_sells = []
        self.canceled = []

    def fetch_ticker(self, _symbol):
        return {"last": 100.0}

    def create_limit_buy_order(self, symbol, amount, price):
        if self.limit_buy_raises:
            raise RuntimeError("limit placement rejected")
        self.limit_buys.append((symbol, amount, price))
        return {"id": "entry-1"}

    def create_market_buy_order(self, symbol, cost):
        self.market_buys.append((symbol, cost))
        return {"id": "market-entry-1"}

    def create_limit_sell_order(self, symbol, amount, price):
        self.limit_sells.append((symbol, amount, price))
        return {"id": "exit-1"}

    def create_market_sell_order(self, symbol, amount):
        self.market_sells.append((symbol, amount))
        return {"id": "market-exit-1"}

    def fetch_order(self, order_id, symbol):
        if self.fetch_raises:
            raise RuntimeError("status unavailable")
        return {"id": order_id, "symbol": symbol, "status": self.status}

    def cancel_order(self, order_id, symbol):
        self.canceled.append((order_id, symbol))
        return {"id": order_id, "status": "canceled"}


class OrderSafetyTests(unittest.TestCase):
    def test_position_size_cost_matches_recorded_amount(self):
        get_position_size = load_function("main_multi_symbol.py", "get_position_size")

        amount, cost = get_position_size(
            BalanceExchange(free_usd=100.0),
            "ETH/USD",
            current_price=10.0,
            symbol_risk_slice=0.20,
            leverage=5,
        )

        self.assertEqual(cost, 100.0)
        self.assertEqual(amount, 10.0)
        self.assertEqual(amount * 10.0, cost)

    def test_unfilled_entry_limit_is_canceled_without_market_fallback(self):
        place_entry_order = load_function("main_multi_symbol.py", "place_entry_order")
        exchange = LimitOrderExchange(status="open")

        executed = place_entry_order(
            exchange,
            "ETH/USD",
            "ETH",
            amount=1.0,
            cost=100.0,
            use_limit_orders=True,
            limit_order_offset_pct=0.001,
            enable_trading=True,
        )

        self.assertFalse(executed)
        self.assertEqual(exchange.canceled, [("entry-1", "ETH/USD")])
        self.assertEqual(exchange.market_buys, [])

    def test_uncertain_entry_limit_status_is_canceled_without_market_fallback(self):
        place_entry_order = load_function("main_multi_symbol.py", "place_entry_order")
        exchange = LimitOrderExchange(fetch_raises=True)

        executed = place_entry_order(
            exchange,
            "ETH/USD",
            "ETH",
            amount=1.0,
            cost=100.0,
            use_limit_orders=True,
            limit_order_offset_pct=0.001,
            enable_trading=True,
        )

        self.assertFalse(executed)
        self.assertEqual(exchange.canceled, [("entry-1", "ETH/USD")])
        self.assertEqual(exchange.market_buys, [])

    def test_limit_placement_failure_still_uses_market_fallback(self):
        place_entry_order = load_function("main_multi_symbol.py", "place_entry_order")
        exchange = LimitOrderExchange(limit_buy_raises=True)

        executed = place_entry_order(
            exchange,
            "ETH/USD",
            "ETH",
            amount=1.0,
            cost=100.0,
            use_limit_orders=True,
            limit_order_offset_pct=0.001,
            enable_trading=True,
        )

        self.assertTrue(executed)
        self.assertEqual(exchange.canceled, [])
        self.assertEqual(exchange.market_buys, [("ETH/USD", 100.0)])

    def test_unfilled_exit_limit_is_canceled_before_next_exit_attempt(self):
        place_exit_order = load_function("main_multi_symbol.py", "place_exit_order")
        exchange = LimitOrderExchange(status="open")

        executed = place_exit_order(
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
        self.assertEqual(exchange.canceled, [("exit-1", "ETH/USD")])
        self.assertEqual(exchange.market_sells, [])


if __name__ == "__main__":
    unittest.main()
