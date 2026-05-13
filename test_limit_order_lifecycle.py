#!/usr/bin/env python3
import ast
import pathlib
import types
import unittest


def load_order_helpers():
    source_path = pathlib.Path(__file__).with_name("main_multi_symbol.py")
    module_ast = ast.parse(source_path.read_text())
    wanted = {
        "cancel_unfilled_limit_order",
        "place_entry_order",
        "place_exit_order",
    }
    helper_ast = ast.Module(
        body=[
            node
            for node in module_ast.body
            if isinstance(node, ast.FunctionDef) and node.name in wanted
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(helper_ast)
    namespace = {"time": types.SimpleNamespace(sleep=lambda _: None)}
    exec(compile(helper_ast, str(source_path), "exec"), namespace)
    return namespace["place_entry_order"], namespace["place_exit_order"]


place_entry_order, place_exit_order = load_order_helpers()


class FakeExchange:
    def __init__(self, *, status="open", limit_buy_error=None, limit_sell_error=None, fetch_order_error=None):
        self.status = status
        self.limit_buy_error = limit_buy_error
        self.limit_sell_error = limit_sell_error
        self.fetch_order_error = fetch_order_error
        self.calls = []

    def fetch_ticker(self, symbol):
        self.calls.append(("fetch_ticker", symbol))
        return {"last": 100.0}

    def create_limit_buy_order(self, symbol, amount, price):
        self.calls.append(("create_limit_buy_order", symbol, amount, price))
        if self.limit_buy_error:
            raise self.limit_buy_error
        return {"id": "limit-buy-1"}

    def create_limit_sell_order(self, symbol, amount, price):
        self.calls.append(("create_limit_sell_order", symbol, amount, price))
        if self.limit_sell_error:
            raise self.limit_sell_error
        return {"id": "limit-sell-1"}

    def fetch_order(self, order_id, symbol):
        self.calls.append(("fetch_order", order_id, symbol))
        if self.fetch_order_error:
            raise self.fetch_order_error
        return {"status": self.status}

    def cancel_order(self, order_id, symbol):
        self.calls.append(("cancel_order", order_id, symbol))
        return {"id": order_id, "status": "canceled"}

    def create_market_buy_order(self, symbol, cost):
        self.calls.append(("create_market_buy_order", symbol, cost))
        return {"id": "market-buy-1"}

    def create_market_sell_order(self, symbol, amount):
        self.calls.append(("create_market_sell_order", symbol, amount))
        return {"id": "market-sell-1"}


class LimitOrderLifecycleTests(unittest.TestCase):
    def test_unfilled_limit_entry_is_canceled_without_market_fallback(self):
        exchange = FakeExchange(status="open")

        result = place_entry_order(exchange, "ETH/USD", "ETH", 0.5, 50.0, True, 0.001, True)

        self.assertFalse(result)
        self.assertIn(("cancel_order", "limit-buy-1", "ETH/USD"), exchange.calls)
        self.assertNotIn(("create_market_buy_order", "ETH/USD", 50.0), exchange.calls)

    def test_limit_entry_creation_failure_still_falls_back_to_market_buy(self):
        exchange = FakeExchange(limit_buy_error=RuntimeError("rejected"))

        result = place_entry_order(exchange, "ETH/USD", "ETH", 0.5, 50.0, True, 0.001, True)

        self.assertTrue(result)
        self.assertIn(("create_market_buy_order", "ETH/USD", 50.0), exchange.calls)

    def test_unfilled_limit_exit_is_canceled_without_market_fallback(self):
        exchange = FakeExchange(status="open")

        result = place_exit_order(exchange, "ETH/USD", "ETH", 0.5, "Profit-taking", True, 0.001, True)

        self.assertFalse(result)
        self.assertIn(("cancel_order", "limit-sell-1", "ETH/USD"), exchange.calls)
        self.assertNotIn(("create_market_sell_order", "ETH/USD", 0.5), exchange.calls)

    def test_unconfirmed_limit_exit_is_canceled_without_market_fallback(self):
        exchange = FakeExchange(fetch_order_error=RuntimeError("timeout"))

        result = place_exit_order(exchange, "ETH/USD", "ETH", 0.5, "Profit-taking", True, 0.001, True)

        self.assertFalse(result)
        self.assertIn(("cancel_order", "limit-sell-1", "ETH/USD"), exchange.calls)
        self.assertNotIn(("create_market_sell_order", "ETH/USD", 0.5), exchange.calls)


if __name__ == "__main__":
    unittest.main()
