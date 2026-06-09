import ast
import unittest
from pathlib import Path
from typing import Tuple


REPO_ROOT = Path(__file__).resolve().parent


def load_function(source_file: str, function_name: str, namespace=None):
    namespace = dict(namespace or {})
    source = (REPO_ROOT / source_file).read_text()
    module = ast.parse(source)

    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            function_module = ast.Module(body=[node], type_ignores=[])
            ast.fix_missing_locations(function_module)
            exec(compile(function_module, source_file, "exec"), namespace)
            return namespace[function_name]

    raise AssertionError(f"{function_name} not found in {source_file}")


class FakeExchange:
    def __init__(self, balance):
        self.balance = balance

    def fetch_balance(self):
        return self.balance


class PositionSizingTests(unittest.TestCase):
    def test_multi_symbol_cost_matches_recorded_base_amount(self):
        get_position_size = load_function(
            "main_multi_symbol.py",
            "get_position_size",
            {"Tuple": Tuple},
        )
        exchange = FakeExchange({"USD": {"free": 1000}})

        amount, cost = get_position_size(
            exchange,
            "ETH/USD",
            current_price=100,
            symbol_risk_slice=0.20,
            leverage=5,
        )

        self.assertEqual(amount, 10)
        self.assertEqual(cost, 1000)
        self.assertEqual(amount * 100, cost)

    def test_multi_symbol_uses_usdc_fallback_with_consistent_cost(self):
        get_position_size = load_function(
            "main_multi_symbol.py",
            "get_position_size",
            {"Tuple": Tuple},
        )
        exchange = FakeExchange({"USD": {"free": 0}, "USDC": {"free": 500}})

        amount, cost = get_position_size(
            exchange,
            "BTC/USD",
            current_price=50,
            symbol_risk_slice=0.10,
            leverage=4,
        )

        self.assertEqual(amount, 4)
        self.assertEqual(cost, 200)
        self.assertEqual(amount * 50, cost)

    def test_single_symbol_cost_matches_recorded_base_amount(self):
        exchange = FakeExchange({"USD": {"free": 1000}})
        get_position_size = load_function(
            "main.py",
            "get_position_size",
            {"exchange": exchange, "risk_pct": 0.20, "leverage": 5},
        )

        amount, cost = get_position_size(current_price=100)

        self.assertEqual(amount, 10)
        self.assertEqual(cost, 1000)
        self.assertEqual(amount * 100, cost)

    def test_non_positive_price_returns_no_order_size(self):
        get_position_size = load_function(
            "main_multi_symbol.py",
            "get_position_size",
            {"Tuple": Tuple},
        )
        exchange = FakeExchange({"USD": {"free": 1000}})

        amount, cost = get_position_size(
            exchange,
            "ETH/USD",
            current_price=0,
            symbol_risk_slice=0.20,
            leverage=5,
        )

        self.assertEqual(amount, 0)
        self.assertEqual(cost, 0)


if __name__ == "__main__":
    unittest.main()
