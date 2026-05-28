import ast
import pathlib
import types
import unittest
from typing import Tuple


def load_functions(*function_names):
    source_path = pathlib.Path(__file__).with_name("main_multi_symbol.py")
    module_ast = ast.parse(source_path.read_text())
    selected_nodes = [
        node
        for node in module_ast.body
        if isinstance(node, ast.FunctionDef) and node.name in function_names
    ]

    module = types.ModuleType("main_multi_symbol_under_test")
    module.__dict__["Tuple"] = Tuple
    exec(
        compile(ast.Module(body=selected_nodes, type_ignores=[]), str(source_path), "exec"),
        module.__dict__,
    )
    return module


class FakeExchange:
    def __init__(self):
        self.market_buys = []

    def fetch_balance(self):
        return {"USD": {"free": 1000.0}}

    def create_market_buy_order(self, symbol, cost):
        self.market_buys.append((symbol, cost))
        return {"id": "buy-1"}


class OrderSizingTest(unittest.TestCase):
    def test_position_cost_matches_recorded_base_amount(self):
        helpers = load_functions("get_position_size")
        amount, cost = helpers.get_position_size(
            FakeExchange(),
            "ETH/USD",
            current_price=100.0,
            symbol_risk_slice=0.02,
            leverage=5,
        )

        self.assertEqual(amount, 1.0)
        self.assertEqual(cost, 100.0)
        self.assertEqual(amount * 100.0, cost)

    def test_market_buy_uses_quote_cost_matching_recorded_amount(self):
        helpers = load_functions("get_position_size", "place_entry_order")
        exchange = FakeExchange()
        amount, cost = helpers.get_position_size(
            exchange,
            "ETH/USD",
            current_price=100.0,
            symbol_risk_slice=0.02,
            leverage=5,
        )

        executed = helpers.place_entry_order(
            exchange,
            "ETH/USD",
            "ETH",
            amount,
            cost,
            use_limit_orders=False,
            limit_order_offset_pct=0.001,
            enable_trading=True,
        )

        self.assertTrue(executed)
        self.assertEqual(exchange.market_buys, [("ETH/USD", 100.0)])


if __name__ == "__main__":
    unittest.main()
