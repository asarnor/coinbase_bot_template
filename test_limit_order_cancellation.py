import ast
import types
import unittest
from pathlib import Path


def load_order_helpers():
    source = Path("main_multi_symbol.py").read_text()
    module_ast = ast.parse(source)
    wanted = {"cancel_unfilled_order", "place_entry_order", "place_exit_order"}
    helper_nodes = [
        node for node in module_ast.body
        if isinstance(node, ast.FunctionDef) and node.name in wanted
    ]
    namespace = {"time": types.SimpleNamespace(sleep=lambda _seconds: None)}
    exec(compile(ast.Module(body=helper_nodes, type_ignores=[]), "main_multi_symbol.py", "exec"), namespace)
    return namespace["place_entry_order"], namespace["place_exit_order"]


class FakeExchange:
    def __init__(self):
        self.calls = []
        self.order_status = {"status": "open"}
        self.fetch_order_error = None
        self.limit_buy_error = None
        self.limit_sell_error = None

    def fetch_ticker(self, symbol):
        self.calls.append(("fetch_ticker", symbol))
        return {"last": 100.0}

    def create_limit_buy_order(self, symbol, amount, limit_price):
        self.calls.append(("create_limit_buy_order", symbol, amount, limit_price))
        if self.limit_buy_error:
            raise self.limit_buy_error
        return {"id": "buy-1"}

    def create_limit_sell_order(self, symbol, amount, limit_price):
        self.calls.append(("create_limit_sell_order", symbol, amount, limit_price))
        if self.limit_sell_error:
            raise self.limit_sell_error
        return {"id": "sell-1"}

    def fetch_order(self, order_id, symbol):
        self.calls.append(("fetch_order", order_id, symbol))
        if self.fetch_order_error:
            raise self.fetch_order_error
        return self.order_status

    def cancel_order(self, order_id, symbol):
        self.calls.append(("cancel_order", order_id, symbol))
        return {"id": order_id, "status": "canceled"}

    def create_market_buy_order(self, symbol, cost):
        self.calls.append(("create_market_buy_order", symbol, cost))
        return {"id": "market-buy-1"}

    def create_market_sell_order(self, symbol, amount):
        self.calls.append(("create_market_sell_order", symbol, amount))
        return {"id": "market-sell-1"}


class LimitOrderCancellationTests(unittest.TestCase):
    def test_unfilled_entry_limit_is_canceled_without_market_fallback(self):
        place_entry_order, _ = load_order_helpers()
        exchange = FakeExchange()

        executed = place_entry_order(exchange, "ETH/USD", "ETH", 0.25, 25.0, True, 0.001, True)

        self.assertFalse(executed)
        self.assertIn(("cancel_order", "buy-1", "ETH/USD"), exchange.calls)
        self.assertFalse(any(call[0] == "create_market_buy_order" for call in exchange.calls))


    def test_entry_limit_status_error_does_not_submit_duplicate_market_buy(self):
        place_entry_order, _ = load_order_helpers()
        exchange = FakeExchange()
        exchange.fetch_order_error = RuntimeError("status timeout")

        executed = place_entry_order(exchange, "ETH/USD", "ETH", 0.25, 25.0, True, 0.001, True)

        self.assertFalse(executed)
        self.assertIn(("cancel_order", "buy-1", "ETH/USD"), exchange.calls)
        self.assertFalse(any(call[0] == "create_market_buy_order" for call in exchange.calls))


    def test_limit_entry_create_failure_still_uses_market_fallback(self):
        place_entry_order, _ = load_order_helpers()
        exchange = FakeExchange()
        exchange.limit_buy_error = RuntimeError("limit unavailable")

        executed = place_entry_order(exchange, "ETH/USD", "ETH", 0.25, 25.0, True, 0.001, True)

        self.assertTrue(executed)
        self.assertIn(("create_market_buy_order", "ETH/USD", 25.0), exchange.calls)


    def test_unfilled_exit_limit_is_canceled_without_market_fallback(self):
        _, place_exit_order = load_order_helpers()
        exchange = FakeExchange()

        executed = place_exit_order(exchange, "ETH/USD", "ETH", 0.25, "Profit-taking", True, 0.001, True)

        self.assertFalse(executed)
        self.assertIn(("cancel_order", "sell-1", "ETH/USD"), exchange.calls)
        self.assertFalse(any(call[0] == "create_market_sell_order" for call in exchange.calls))

    def test_exit_limit_status_error_does_not_submit_duplicate_market_sell(self):
        _, place_exit_order = load_order_helpers()
        exchange = FakeExchange()
        exchange.fetch_order_error = RuntimeError("status timeout")

        executed = place_exit_order(exchange, "ETH/USD", "ETH", 0.25, "Profit-taking", True, 0.001, True)

        self.assertFalse(executed)
        self.assertIn(("cancel_order", "sell-1", "ETH/USD"), exchange.calls)
        self.assertFalse(any(call[0] == "create_market_sell_order" for call in exchange.calls))


if __name__ == "__main__":
    unittest.main()

