import ast
import types
import unittest
from typing import Dict, Tuple


def load_bot_helpers(*function_names):
    with open("main_multi_symbol.py", "r", encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename="main_multi_symbol.py")

    selected = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in function_names
    ]
    module = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(module)

    namespace = {
        "Dict": Dict,
        "Tuple": Tuple,
        "time": types.SimpleNamespace(sleep=lambda _seconds: None),
    }
    exec(compile(module, "main_multi_symbol.py", "exec"), namespace)
    return {name: namespace[name] for name in function_names}


class FakeSizingExchange:
    def fetch_balance(self):
        return {"USD": {"free": 1000.0}}


class FakeLimitExchange:
    def __init__(self, status="open", cancel_raises=False):
        self.status = status
        self.cancel_raises = cancel_raises
        self.created_market_buys = []
        self.created_market_sells = []
        self.canceled_orders = []

    def fetch_ticker(self, symbol):
        return {"last": 100.0}

    def create_limit_buy_order(self, symbol, amount, limit_price):
        return {"id": "buy-1"}

    def create_limit_sell_order(self, symbol, amount, limit_price):
        return {"id": "sell-1"}

    def fetch_order(self, order_id, symbol):
        return {"status": self.status}

    def cancel_order(self, order_id, symbol):
        if self.cancel_raises:
            raise RuntimeError("cancel failed")
        self.canceled_orders.append((order_id, symbol))

    def create_market_buy_order(self, symbol, cost):
        self.created_market_buys.append((symbol, cost))
        return {"id": "market-buy-1"}

    def create_market_sell_order(self, symbol, amount):
        self.created_market_sells.append((symbol, amount))
        return {"id": "market-sell-1"}


class OrderSafetyTests(unittest.TestCase):
    def test_position_size_returns_quote_value_matching_base_amount(self):
        helpers = load_bot_helpers("get_position_size")
        amount, cost = helpers["get_position_size"](
            FakeSizingExchange(),
            "ETH/USD",
            current_price=2500.0,
            symbol_risk_slice=0.2,
            leverage=5,
        )

        self.assertEqual(amount, 0.4)
        self.assertEqual(cost, 1000.0)
        self.assertEqual(amount * 2500.0, cost)

    def test_unfilled_limit_entry_is_canceled_without_market_fallback(self):
        helpers = load_bot_helpers("cancel_unfilled_limit_order", "place_entry_order")
        exchange = FakeLimitExchange(status="open")

        executed = helpers["place_entry_order"](
            exchange,
            "ETH/USD",
            "ETH",
            amount=1.0,
            cost=100.0,
            use_limit_orders=True,
            limit_order_offset_pct=0.001,
            enable_trading=True,
        )

        self.assertFalse(executed)
        self.assertEqual(exchange.canceled_orders, [("buy-1", "ETH/USD")])
        self.assertEqual(exchange.created_market_buys, [])

    def test_unfilled_limit_exit_is_canceled_without_market_fallback(self):
        helpers = load_bot_helpers("cancel_unfilled_limit_order", "place_exit_order")
        exchange = FakeLimitExchange(status="open")

        executed = helpers["place_exit_order"](
            exchange,
            "ETH/USD",
            "ETH",
            amount=1.0,
            reason="Profit-taking",
            use_limit_orders=True,
            limit_order_offset_pct=0.001,
            enable_trading=True,
        )

        self.assertFalse(executed)
        self.assertEqual(exchange.canceled_orders, [("sell-1", "ETH/USD")])
        self.assertEqual(exchange.created_market_sells, [])

    def test_cancel_failure_does_not_trigger_market_fallback(self):
        helpers = load_bot_helpers("cancel_unfilled_limit_order", "place_entry_order")
        exchange = FakeLimitExchange(status="open", cancel_raises=True)

        executed = helpers["place_entry_order"](
            exchange,
            "ETH/USD",
            "ETH",
            amount=1.0,
            cost=100.0,
            use_limit_orders=True,
            limit_order_offset_pct=0.001,
            enable_trading=True,
        )

        self.assertFalse(executed)
        self.assertEqual(exchange.created_market_buys, [])


if __name__ == "__main__":
    unittest.main()
