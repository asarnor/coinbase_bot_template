import ast
import pathlib
import unittest
from typing import Tuple


def load_function(function_name):
    source_path = pathlib.Path(__file__).with_name("main_multi_symbol.py")
    tree = ast.parse(source_path.read_text())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            module = ast.Module(body=[node], type_ignores=[])
            ast.fix_missing_locations(module)
            namespace = {"Tuple": Tuple}
            exec(compile(module, str(source_path), "exec"), namespace)
            return namespace[function_name]
    raise AssertionError(f"{function_name} not found")


get_position_size = load_function("get_position_size")


class FakeExchange:
    def __init__(self, balance):
        self._balance = balance

    def fetch_balance(self):
        return self._balance


class OrderSizingTests(unittest.TestCase):
    def test_quote_cost_matches_recorded_base_amount(self):
        exchange = FakeExchange({"USD": {"free": 1000.0}})

        amount, cost = get_position_size(
            exchange,
            "ETH/USD",
            current_price=100.0,
            symbol_risk_slice=0.10,
            leverage=5,
        )

        self.assertEqual(amount, 5.0)
        self.assertEqual(cost, 500.0)
        self.assertAlmostEqual(amount * 100.0, cost)

    def test_usdc_fallback_uses_same_notional_invariant(self):
        exchange = FakeExchange({"USD": {"free": 0.0}, "USDC": {"free": 200.0}})

        amount, cost = get_position_size(
            exchange,
            "BTC/USD",
            current_price=50.0,
            symbol_risk_slice=0.20,
            leverage=3,
        )

        self.assertEqual(amount, 2.4)
        self.assertEqual(cost, 120.0)
        self.assertAlmostEqual(amount * 50.0, cost)

    def test_non_positive_price_returns_no_order_size(self):
        exchange = FakeExchange({"USD": {"free": 1000.0}})

        amount, cost = get_position_size(
            exchange,
            "ETH/USD",
            current_price=0.0,
            symbol_risk_slice=0.10,
            leverage=5,
        )

        self.assertEqual(amount, 0)
        self.assertEqual(cost, 0)


if __name__ == "__main__":
    unittest.main()
