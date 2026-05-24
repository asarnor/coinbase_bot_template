import ast
import pathlib
import types
import unittest
from typing import Tuple


FUNCTIONS_UNDER_TEST = {
    "get_position_size",
    "place_entry_order",
    "place_exit_order",
}


class NoSleep:
    @staticmethod
    def sleep(_seconds):
        return None


def load_order_helpers():
    source_path = pathlib.Path(__file__).with_name("main_multi_symbol.py")
    module_ast = ast.parse(source_path.read_text())
    selected_nodes = [
        node
        for node in module_ast.body
        if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS_UNDER_TEST
    ]
    namespace = {"Tuple": Tuple, "time": NoSleep}
    ast.fix_missing_locations(module_ast)
    compiled = compile(ast.Module(body=selected_nodes, type_ignores=[]), str(source_path), "exec")
    exec(compiled, namespace)
    return namespace


HELPERS = load_order_helpers()


class FakeBalanceExchange:
    def fetch_balance(self):
        return {"USD": {"free": 1000.0}}


class FakeMarketEntryExchange:
    def __init__(self):
        self.market_buys = []

    def create_market_buy_order(self, symbol, cost):
        self.market_buys.append((symbol, cost))
        return {"id": "market-buy-1", "filled": 4.75}


class FakeLimitEntryFetchFailureExchange:
    def __init__(self):
        self.market_buy_called = False
        self.cancelled = []

    def fetch_ticker(self, _symbol):
        return {"last": 100.0}

    def create_limit_buy_order(self, _symbol, _amount, _limit_price):
        return {"id": "limit-buy-1"}

    def fetch_order(self, _order_id, _symbol):
        raise RuntimeError("temporary status API failure")

    def cancel_order(self, order_id, symbol):
        self.cancelled.append((order_id, symbol))

    def create_market_buy_order(self, _symbol, _cost):
        self.market_buy_called = True
        raise AssertionError("market fallback must not run after a limit order was placed")


class FakeLimitExitOpenExchange:
    def __init__(self):
        self.market_sell_called = False
        self.cancelled = []

    def fetch_ticker(self, _symbol):
        return {"last": 100.0}

    def create_limit_sell_order(self, _symbol, _amount, _limit_price):
        return {"id": "limit-sell-1"}

    def fetch_order(self, _order_id, _symbol):
        return {"status": "open"}

    def cancel_order(self, order_id, symbol):
        self.cancelled.append((order_id, symbol))

    def create_market_sell_order(self, _symbol, _amount):
        self.market_sell_called = True
        raise AssertionError("market fallback must not run while a limit exit exists")


class OrderSafetyTests(unittest.TestCase):
    def test_position_size_cost_matches_recorded_amount(self):
        amount, cost = HELPERS["get_position_size"](
            FakeBalanceExchange(),
            "ETH/USD",
            current_price=100.0,
            symbol_risk_slice=0.10,
            leverage=5,
        )

        self.assertEqual(amount, 5.0)
        self.assertEqual(cost, 500.0)
        self.assertEqual(amount * 100.0, cost)

    def test_market_entry_returns_actual_filled_amount(self):
        exchange = FakeMarketEntryExchange()

        executed, filled_amount = HELPERS["place_entry_order"](
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
        self.assertEqual(filled_amount, 4.75)
        self.assertEqual(exchange.market_buys, [("ETH/USD", 500.0)])

    def test_limit_entry_status_failure_cancels_without_market_fallback(self):
        exchange = FakeLimitEntryFetchFailureExchange()

        executed, filled_amount = HELPERS["place_entry_order"](
            exchange,
            "ETH/USD",
            "ETH",
            amount=5.0,
            cost=500.0,
            use_limit_orders=True,
            limit_order_offset_pct=0.001,
            enable_trading=True,
        )

        self.assertFalse(executed)
        self.assertEqual(filled_amount, 0.0)
        self.assertEqual(exchange.cancelled, [("limit-buy-1", "ETH/USD")])
        self.assertFalse(exchange.market_buy_called)

    def test_open_limit_exit_cancels_without_market_fallback(self):
        exchange = FakeLimitExitOpenExchange()

        executed = HELPERS["place_exit_order"](
            exchange,
            "ETH/USD",
            "ETH",
            amount=5.0,
            reason="Profit-taking",
            use_limit_orders=True,
            limit_order_offset_pct=0.001,
            enable_trading=True,
        )

        self.assertFalse(executed)
        self.assertEqual(exchange.cancelled, [("limit-sell-1", "ETH/USD")])
        self.assertFalse(exchange.market_sell_called)


if __name__ == "__main__":
    unittest.main()
