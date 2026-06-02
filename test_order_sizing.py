import ast
import pathlib
import unittest
from typing import Tuple


ROOT = pathlib.Path(__file__).resolve().parent


class FakeExchange:
    def __init__(self, balance):
        self._balance = balance

    def fetch_balance(self):
        return self._balance


def load_function(module_path, function_name, namespace=None):
    namespace = {} if namespace is None else dict(namespace)
    source = (ROOT / module_path).read_text()
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            module = ast.Module(body=[node], type_ignores=[])
            ast.fix_missing_locations(module)
            exec(compile(module, str(ROOT / module_path), "exec"), namespace)
            return namespace[function_name]
    raise AssertionError(f"{function_name} not found in {module_path}")


class OrderSizingTests(unittest.TestCase):
    def test_multi_symbol_position_amount_matches_market_buy_cost(self):
        get_position_size = load_function(
            "main_multi_symbol.py",
            "get_position_size",
            {"Tuple": Tuple},
        )

        amount, cost = get_position_size(
            FakeExchange({"USD": {"free": 1000.0}}),
            "ETH/USD",
            current_price=250.0,
            symbol_risk_slice=0.20,
            leverage=5,
        )

        self.assertEqual(cost, 1000.0)
        self.assertEqual(amount, 4.0)
        self.assertAlmostEqual(amount * 250.0, cost)

    def test_multi_symbol_uses_usdc_when_usd_is_unavailable(self):
        get_position_size = load_function(
            "main_multi_symbol.py",
            "get_position_size",
            {"Tuple": Tuple},
        )

        amount, cost = get_position_size(
            FakeExchange({"USDC": {"free": 500.0}}),
            "BTC/USD",
            current_price=100.0,
            symbol_risk_slice=0.10,
            leverage=3,
        )

        self.assertEqual(cost, 150.0)
        self.assertEqual(amount, 1.5)
        self.assertAlmostEqual(amount * 100.0, cost)

    def test_single_symbol_position_amount_matches_market_buy_cost(self):
        get_position_size = load_function(
            "main.py",
            "get_position_size",
            {
                "exchange": FakeExchange({"USD": {"free": 1000.0}}),
                "risk_pct": 0.20,
                "leverage": 5,
            },
        )

        amount, cost = get_position_size(current_price=250.0)

        self.assertEqual(cost, 1000.0)
        self.assertEqual(amount, 4.0)
        self.assertAlmostEqual(amount * 250.0, cost)


if __name__ == "__main__":
    unittest.main()
