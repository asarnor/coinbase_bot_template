#!/usr/bin/env python3
import ast
import pathlib
import unittest
from typing import Tuple


def load_function(function_name):
    module_path = pathlib.Path(__file__).with_name("main_multi_symbol.py")
    module_ast = ast.parse(module_path.read_text(encoding="utf-8"))
    for node in module_ast.body:
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            namespace = {"Tuple": Tuple}
            exec(compile(ast.Module(body=[node], type_ignores=[]), str(module_path), "exec"), namespace)
            return namespace[function_name]
    raise AssertionError(f"{function_name} not found")


get_position_size = load_function("get_position_size")


class FakeExchange:
    def __init__(self, balance):
        self._balance = balance

    def fetch_balance(self):
        return self._balance


class OrderSizingTest(unittest.TestCase):
    def test_market_buy_cost_matches_recorded_base_amount(self):
        exchange = FakeExchange({"USD": {"free": 1_000.0}})

        amount, cost = get_position_size(
            exchange,
            symbol="ETH/USD",
            current_price=2_500.0,
            symbol_risk_slice=0.05,
            leverage=5,
        )

        self.assertEqual(cost, 250.0)
        self.assertEqual(amount, 0.1)
        self.assertAlmostEqual(amount * 2_500.0, cost)

    def test_usdc_fallback_uses_same_notional_contract(self):
        exchange = FakeExchange({"USD": {"free": 0.0}, "USDC": {"free": 200.0}})

        amount, cost = get_position_size(
            exchange,
            symbol="BTC/USD",
            current_price=50_000.0,
            symbol_risk_slice=0.10,
            leverage=3,
        )

        self.assertEqual(cost, 60.0)
        self.assertAlmostEqual(amount, 0.0012)
        self.assertAlmostEqual(amount * 50_000.0, cost)


if __name__ == "__main__":
    unittest.main()
