import ast
import pathlib
import unittest
from typing import Tuple


def load_main_helpers(*function_names):
    source_path = pathlib.Path(__file__).with_name("main_multi_symbol.py")
    tree = ast.parse(source_path.read_text())
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in function_names
    ]
    module = ast.Module(body=functions, type_ignores=[])
    namespace = {"Tuple": Tuple}
    exec(compile(ast.fix_missing_locations(module), str(source_path), "exec"), namespace)
    return {name: namespace[name] for name in function_names}


helpers = load_main_helpers("get_position_size", "place_entry_order")
get_position_size = helpers["get_position_size"]
place_entry_order = helpers["place_entry_order"]


class BalanceExchange:
    def __init__(self, free_usd):
        self.free_usd = free_usd

    def fetch_balance(self):
        return {"USD": {"free": self.free_usd}}


class MarketBuyExchange:
    def __init__(self):
        self.market_buy_calls = []

    def create_market_buy_order(self, symbol, amount, params=None):
        self.market_buy_calls.append((symbol, amount, params))
        return {"id": "market-buy-1"}


class FailingLimitExchange(MarketBuyExchange):
    def fetch_ticker(self, symbol):
        return {"last": 100.0}

    def create_limit_buy_order(self, symbol, amount, limit_price):
        raise RuntimeError("limit rejected")


class OrderSizingTests(unittest.TestCase):
    def test_position_cost_matches_leveraged_amount(self):
        amount, cost = get_position_size(
            BalanceExchange(free_usd=1000.0),
            "ETH/USD",
            current_price=100.0,
            symbol_risk_slice=0.10,
            leverage=5,
        )

        self.assertEqual(amount, 5.0)
        self.assertEqual(cost, 500.0)
        self.assertEqual(cost, amount * 100.0)

    def test_market_entry_passes_quote_cost_explicitly(self):
        exchange = MarketBuyExchange()

        executed = place_entry_order(
            exchange,
            "ETH/USD",
            "ETH",
            amount=5.0,
            cost=500.0,
            use_limit_orders=False,
            limit_order_offset_pct=0.001,
            enable_trading=True,
        )

        self.assertTrue(executed)
        self.assertEqual(
            exchange.market_buy_calls,
            [("ETH/USD", 5.0, {"cost": 500.0})],
        )

    def test_limit_entry_fallback_passes_quote_cost_explicitly(self):
        exchange = FailingLimitExchange()

        executed = place_entry_order(
            exchange,
            "ETH/USD",
            "ETH",
            amount=5.0,
            cost=500.0,
            use_limit_orders=True,
            limit_order_offset_pct=0.001,
            enable_trading=True,
        )

        self.assertTrue(executed)
        self.assertEqual(
            exchange.market_buy_calls,
            [("ETH/USD", 5.0, {"cost": 500.0})],
        )


if __name__ == "__main__":
    unittest.main()
