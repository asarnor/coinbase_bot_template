import ast
import types
import unittest
from pathlib import Path
from typing import Dict, List, Tuple


def load_main_helpers():
    helper_names = {
        "get_order_filled_amount",
        "cancel_limit_order",
        "reduce_position_after_fill",
        "configure_effective_leverage",
        "place_entry_order",
        "place_exit_order",
    }
    source = Path("main_multi_symbol.py").read_text()
    tree = ast.parse(source)
    selected = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in helper_names
    ]
    module = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "Dict": Dict,
        "List": List,
        "Tuple": Tuple,
        "time": types.SimpleNamespace(sleep=lambda _seconds: None),
    }
    exec(compile(module, "main_multi_symbol.py", "exec"), namespace)
    return types.SimpleNamespace(**{name: namespace[name] for name in helper_names})


helpers = load_main_helpers()


class FakeExchange:
    def __init__(self, order_status=None, fetch_error=None, cancel_error=None):
        self.order_status = order_status or {"status": "open", "filled": 0}
        self.fetch_error = fetch_error
        self.cancel_error = cancel_error
        self.canceled_orders = []
        self.market_buys = 0
        self.market_sells = 0
        self.leverage_calls = []

    def fetch_ticker(self, symbol):
        return {"last": 100.0}

    def create_limit_buy_order(self, symbol, amount, limit_price):
        return {"id": "buy-1"}

    def create_limit_sell_order(self, symbol, amount, limit_price):
        return {"id": "sell-1"}

    def fetch_order(self, order_id, symbol):
        if self.fetch_error:
            raise self.fetch_error
        return self.order_status

    def cancel_order(self, order_id, symbol):
        if self.cancel_error:
            raise self.cancel_error
        self.canceled_orders.append((order_id, symbol))
        return {"id": order_id, "status": "canceled"}

    def create_market_buy_order(self, symbol, cost):
        self.market_buys += 1
        return {"id": "market-buy-1", "filled": cost / 100.0}

    def create_market_sell_order(self, symbol, amount):
        self.market_sells += 1
        return {"id": "market-sell-1", "filled": amount}

    def set_leverage(self, leverage, symbol):
        self.leverage_calls.append((leverage, symbol))


class OrderExecutionSafetyTests(unittest.TestCase):
    def test_unfilled_limit_entry_is_canceled_without_market_fallback(self):
        exchange = FakeExchange(order_status={"status": "open", "filled": 0})

        executed, filled_amount = helpers.place_entry_order(
            exchange,
            "ETH/USD",
            "ETH",
            amount=2.0,
            cost=200.0,
            use_limit_orders=True,
            limit_order_offset_pct=0.001,
            enable_trading=True,
        )

        self.assertFalse(executed)
        self.assertEqual(filled_amount, 0.0)
        self.assertEqual(exchange.canceled_orders, [("buy-1", "ETH/USD")])
        self.assertEqual(exchange.market_buys, 0)

    def test_uncertain_limit_entry_is_canceled_without_market_fallback(self):
        exchange = FakeExchange(fetch_error=RuntimeError("status unavailable"))

        executed, filled_amount = helpers.place_entry_order(
            exchange,
            "ETH/USD",
            "ETH",
            amount=2.0,
            cost=200.0,
            use_limit_orders=True,
            limit_order_offset_pct=0.001,
            enable_trading=True,
        )

        self.assertFalse(executed)
        self.assertEqual(filled_amount, 0.0)
        self.assertEqual(exchange.canceled_orders, [("buy-1", "ETH/USD")])
        self.assertEqual(exchange.market_buys, 0)

    def test_partial_limit_entry_reports_filled_amount_after_canceling_remainder(self):
        exchange = FakeExchange(order_status={"status": "open", "filled": 0.4})

        executed, filled_amount = helpers.place_entry_order(
            exchange,
            "ETH/USD",
            "ETH",
            amount=2.0,
            cost=200.0,
            use_limit_orders=True,
            limit_order_offset_pct=0.001,
            enable_trading=True,
        )

        self.assertTrue(executed)
        self.assertEqual(filled_amount, 0.4)
        self.assertEqual(exchange.canceled_orders, [("buy-1", "ETH/USD")])

    def test_unfilled_limit_exit_is_canceled_without_market_fallback(self):
        exchange = FakeExchange(order_status={"status": "open", "filled": 0})

        executed, filled_amount = helpers.place_exit_order(
            exchange,
            "ETH/USD",
            "ETH",
            amount=2.0,
            reason="Profit-taking",
            use_limit_orders=True,
            limit_order_offset_pct=0.001,
            enable_trading=True,
        )

        self.assertFalse(executed)
        self.assertEqual(filled_amount, 0.0)
        self.assertEqual(exchange.canceled_orders, [("sell-1", "ETH/USD")])
        self.assertEqual(exchange.market_sells, 0)

    def test_leverage_failure_falls_back_to_spot_sizing(self):
        class RejectsLeverage(FakeExchange):
            def set_leverage(self, leverage, symbol):
                raise RuntimeError("leverage not supported")

        effective_leverage, message = helpers.configure_effective_leverage(
            RejectsLeverage(),
            ["ETH/USD", "BTC/USD"],
            5,
        )

        self.assertEqual(effective_leverage, 1)
        self.assertIn("leverage not supported", message)

    def test_leverage_success_keeps_requested_sizing(self):
        exchange = FakeExchange()

        effective_leverage, message = helpers.configure_effective_leverage(
            exchange,
            ["ETH/USD", "BTC/USD"],
            5,
        )

        self.assertEqual(effective_leverage, 5)
        self.assertEqual(message, "")
        self.assertEqual(exchange.leverage_calls, [(5, "ETH/USD"), (5, "BTC/USD")])


if __name__ == "__main__":
    unittest.main()
