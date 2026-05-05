#!/usr/bin/env python3
import ast
import pathlib
import unittest


def load_order_helpers():
    source_path = pathlib.Path(__file__).with_name("main_multi_symbol.py")
    module = ast.parse(source_path.read_text())
    wanted = {"cancel_open_limit_order", "place_entry_order", "place_exit_order"}
    helper_nodes = [
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name in wanted
    ]
    compiled = compile(ast.Module(body=helper_nodes, type_ignores=[]), str(source_path), "exec")

    class NoopTime:
        @staticmethod
        def sleep(_seconds):
            return None

    namespace = {"time": NoopTime}
    exec(compiled, namespace)
    return namespace


HELPERS = load_order_helpers()
place_entry_order = HELPERS["place_entry_order"]
place_exit_order = HELPERS["place_exit_order"]


class FakeExchange:
    def __init__(self, order_status):
        self.order_status = order_status
        self.cancelled_orders = []
        self.market_buys = []
        self.market_sells = []

    def fetch_ticker(self, _symbol):
        return {"last": 100.0}

    def create_limit_buy_order(self, _symbol, _amount, _limit_price):
        return {"id": "buy-1"}

    def create_limit_sell_order(self, _symbol, _amount, _limit_price):
        return {"id": "sell-1"}

    def fetch_order(self, _order_id, _symbol):
        if isinstance(self.order_status, Exception):
            raise self.order_status
        return {"status": self.order_status}

    def cancel_order(self, order_id, symbol):
        self.cancelled_orders.append((order_id, symbol))
        return {"id": order_id, "status": "canceled"}

    def create_market_buy_order(self, _symbol, cost):
        self.market_buys.append(cost)
        return {"id": "market-buy-1"}

    def create_market_sell_order(self, _symbol, amount):
        self.market_sells.append(amount)
        return {"id": "market-sell-1"}


class LimitOrderCancellationTest(unittest.TestCase):
    def test_unfilled_entry_limit_order_is_cancelled(self):
        exchange = FakeExchange(order_status="open")

        result = place_entry_order(
            exchange,
            "ETH/USD",
            "ETH",
            amount=1.25,
            cost=125.0,
            use_limit_orders=True,
            limit_order_offset_pct=0.001,
            enable_trading=True,
        )

        self.assertFalse(result)
        self.assertEqual(exchange.cancelled_orders, [("buy-1", "ETH/USD")])
        self.assertEqual(exchange.market_buys, [])

    def test_unverified_entry_limit_order_is_cancelled(self):
        exchange = FakeExchange(order_status=RuntimeError("temporary status outage"))

        result = place_entry_order(
            exchange,
            "ETH/USD",
            "ETH",
            amount=1.25,
            cost=125.0,
            use_limit_orders=True,
            limit_order_offset_pct=0.001,
            enable_trading=True,
        )

        self.assertFalse(result)
        self.assertEqual(exchange.cancelled_orders, [("buy-1", "ETH/USD")])
        self.assertEqual(exchange.market_buys, [])

    def test_unfilled_exit_limit_order_is_cancelled_without_market_fallback(self):
        exchange = FakeExchange(order_status="open")

        result = place_exit_order(
            exchange,
            "ETH/USD",
            "ETH",
            amount=1.25,
            reason="Profit-taking",
            use_limit_orders=True,
            limit_order_offset_pct=0.001,
            enable_trading=True,
        )

        self.assertFalse(result)
        self.assertEqual(exchange.cancelled_orders, [("sell-1", "ETH/USD")])
        self.assertEqual(exchange.market_sells, [])

    def test_closed_limit_orders_are_not_cancelled(self):
        exchange = FakeExchange(order_status="closed")

        result = place_exit_order(
            exchange,
            "ETH/USD",
            "ETH",
            amount=1.25,
            reason="Profit-taking",
            use_limit_orders=True,
            limit_order_offset_pct=0.001,
            enable_trading=True,
        )

        self.assertTrue(result)
        self.assertEqual(exchange.cancelled_orders, [])


if __name__ == "__main__":
    unittest.main()
