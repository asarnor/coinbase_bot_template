import ast
import time
import unittest
from pathlib import Path


def load_order_helpers():
    source = Path("main_multi_symbol.py").read_text()
    module_ast = ast.parse(source)
    helper_names = {"cancel_order_safely", "cancel_open_orders", "place_entry_order", "place_exit_order"}
    helper_nodes = [
        node
        for node in module_ast.body
        if isinstance(node, ast.FunctionDef) and node.name in helper_names
    ]
    helpers_ast = ast.Module(
        body=[
            ast.Import(names=[ast.alias(name="time")]),
            ast.ImportFrom(module="typing", names=[ast.alias(name="Optional")], level=0),
            *helper_nodes,
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(helpers_ast)
    namespace = {}
    exec(compile(helpers_ast, filename="main_multi_symbol.py", mode="exec"), namespace)
    namespace["time"].sleep = lambda _seconds: None
    return namespace


helpers = load_order_helpers()
place_entry_order = helpers["place_entry_order"]
place_exit_order = helpers["place_exit_order"]


class FakeExchange:
    def __init__(self, order_status="open", open_orders=None):
        self.order_status = order_status
        self.open_orders = list(open_orders or [])
        self.created_limit_buys = []
        self.created_limit_sells = []
        self.created_market_buys = []
        self.created_market_sells = []
        self.canceled_orders = []

    def fetch_ticker(self, _symbol):
        return {"last": 100.0}

    def fetch_open_orders(self, _symbol):
        return list(self.open_orders)

    def cancel_order(self, order_id, _symbol):
        self.canceled_orders.append(order_id)

    def create_limit_buy_order(self, symbol, amount, price):
        self.created_limit_buys.append((symbol, amount, price))
        return {"id": "entry-1"}

    def create_limit_sell_order(self, symbol, amount, price):
        self.created_limit_sells.append((symbol, amount, price))
        return {"id": "exit-1"}

    def fetch_order(self, order_id, _symbol):
        return {"id": order_id, "status": self.order_status}

    def create_market_buy_order(self, symbol, cost):
        self.created_market_buys.append((symbol, cost))
        return {"id": "market-buy-1"}

    def create_market_sell_order(self, symbol, amount):
        self.created_market_sells.append((symbol, amount))
        return {"id": "market-sell-1"}


class LimitOrderCancellationTests(unittest.TestCase):
    def test_unfilled_entry_limit_is_canceled_before_returning_unfilled(self):
        exchange = FakeExchange(order_status="open")

        filled = place_entry_order(
            exchange,
            "ETH/USD",
            "ETH",
            amount=0.25,
            cost=25.0,
            use_limit_orders=True,
            limit_order_offset_pct=0.001,
            enable_trading=True,
        )

        self.assertFalse(filled)
        self.assertEqual(exchange.created_limit_buys, [("ETH/USD", 0.25, 99.9)])
        self.assertEqual(exchange.canceled_orders, ["entry-1"])
        self.assertEqual(exchange.created_market_buys, [])

    def test_existing_entry_limits_are_canceled_before_new_buy(self):
        exchange = FakeExchange(
            order_status="closed",
            open_orders=[{"id": "old-buy", "side": "buy"}, {"id": "old-sell", "side": "sell"}],
        )

        filled = place_entry_order(
            exchange,
            "ETH/USD",
            "ETH",
            amount=0.25,
            cost=25.0,
            use_limit_orders=True,
            limit_order_offset_pct=0.001,
            enable_trading=True,
        )

        self.assertTrue(filled)
        self.assertEqual(exchange.canceled_orders, ["old-buy"])
        self.assertEqual(exchange.created_limit_buys, [("ETH/USD", 0.25, 99.9)])

    def test_unfilled_exit_limit_is_canceled_before_returning_unfilled(self):
        exchange = FakeExchange(order_status="open")

        filled = place_exit_order(
            exchange,
            "ETH/USD",
            "ETH",
            amount=0.25,
            reason="Profit-taking",
            use_limit_orders=True,
            limit_order_offset_pct=0.001,
            enable_trading=True,
        )

        self.assertFalse(filled)
        self.assertEqual(exchange.created_limit_sells, [("ETH/USD", 0.25, 100.1)])
        self.assertEqual(exchange.canceled_orders, ["exit-1"])
        self.assertEqual(exchange.created_market_sells, [])

    def test_forced_market_exit_cancels_existing_sell_orders_first(self):
        exchange = FakeExchange(open_orders=[{"id": "old-exit", "side": "sell"}])

        filled = place_exit_order(
            exchange,
            "ETH/USD",
            "ETH",
            amount=0.25,
            reason="Stop-loss",
            use_limit_orders=True,
            limit_order_offset_pct=0.001,
            enable_trading=True,
            force_market=True,
        )

        self.assertTrue(filled)
        self.assertEqual(exchange.canceled_orders, ["old-exit"])
        self.assertEqual(exchange.created_limit_sells, [])
        self.assertEqual(exchange.created_market_sells, [("ETH/USD", 0.25)])


if __name__ == "__main__":
    unittest.main()
