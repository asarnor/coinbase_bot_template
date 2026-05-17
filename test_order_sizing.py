import ast
import pathlib
import unittest


def load_get_position_size():
    source_path = pathlib.Path(__file__).with_name("main_multi_symbol.py")
    module_ast = ast.parse(source_path.read_text())
    function_node = next(
        node
        for node in module_ast.body
        if isinstance(node, ast.FunctionDef) and node.name == "get_position_size"
    )
    test_module = ast.Module(
        body=[
            ast.ImportFrom(module="typing", names=[ast.alias(name="Tuple")], level=0),
            function_node,
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(test_module)
    namespace = {}
    exec(compile(test_module, str(source_path), "exec"), namespace)
    return namespace["get_position_size"]


class FakeExchange:
    def __init__(self, balance):
        self.balance = balance

    def fetch_balance(self):
        return self.balance


class PositionSizingTests(unittest.TestCase):
    def setUp(self):
        self.get_position_size = load_get_position_size()

    def test_quote_cost_matches_recorded_base_amount(self):
        amount, cost = self.get_position_size(
            FakeExchange({"USD": {"free": 1000.0}}),
            "ETH/USD",
            current_price=2000.0,
            symbol_risk_slice=0.10,
            leverage=5,
        )

        self.assertAlmostEqual(amount, 0.25)
        self.assertAlmostEqual(cost, 500.0)
        self.assertAlmostEqual(amount * 2000.0, cost)

    def test_uses_usdc_balance_when_usd_is_unavailable(self):
        amount, cost = self.get_position_size(
            FakeExchange({"USD": {"free": 0.0}, "USDC": {"free": 250.0}}),
            "BTC/USD",
            current_price=50000.0,
            symbol_risk_slice=0.20,
            leverage=2,
        )

        self.assertAlmostEqual(amount, 0.002)
        self.assertAlmostEqual(cost, 100.0)
        self.assertAlmostEqual(amount * 50000.0, cost)


if __name__ == "__main__":
    unittest.main()
