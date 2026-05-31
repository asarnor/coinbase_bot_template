#!/usr/bin/env python3
import ast
import pathlib
import typing
import unittest


def load_get_position_size():
    source_path = pathlib.Path(__file__).with_name("main_multi_symbol.py")
    module = ast.parse(source_path.read_text())
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == "get_position_size":
            compiled = compile(ast.Module(body=[node], type_ignores=[]), str(source_path), "exec")
            namespace = {"Tuple": typing.Tuple}
            exec(compiled, namespace)
            return namespace[node.name]
    raise AssertionError("get_position_size not found")


class FakeExchange:
    def __init__(self, balance):
        self.balance = balance

    def fetch_balance(self):
        return self.balance


class OrderSizingTests(unittest.TestCase):
    def setUp(self):
        self.get_position_size = load_get_position_size()

    def test_market_buy_cost_matches_recorded_base_amount(self):
        amount, cost = self.get_position_size(
            FakeExchange({"USD": {"free": 1000.0}}),
            "ETH/USD",
            current_price=50.0,
            symbol_risk_slice=0.10,
            leverage=5,
        )

        self.assertEqual(amount, 10.0)
        self.assertEqual(cost, 500.0)
        self.assertEqual(cost, amount * 50.0)

    def test_usdc_balance_fallback_uses_same_cost_invariant(self):
        amount, cost = self.get_position_size(
            FakeExchange({"USD": {"free": 0.0}, "USDC": {"free": 200.0}}),
            "BTC/USD",
            current_price=100.0,
            symbol_risk_slice=0.25,
            leverage=2,
        )

        self.assertEqual(amount, 1.0)
        self.assertEqual(cost, 100.0)
        self.assertEqual(cost, amount * 100.0)


if __name__ == "__main__":
    unittest.main()
