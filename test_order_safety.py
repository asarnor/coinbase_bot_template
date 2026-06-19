import ast
import unittest
from pathlib import Path
from typing import Dict, List, Tuple


class NoSleep:
    @staticmethod
    def sleep(_seconds):
        return None


def load_order_helpers():
    source = Path("main_multi_symbol.py").read_text()
    module = ast.parse(source)
    wanted = {
        "cancel_limit_order",
        "place_entry_order",
        "place_exit_order",
        "get_position_size",
    }
    selected = [
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name in wanted
    ]
    namespace = {
        "Dict": Dict,
        "List": List,
        "Tuple": Tuple,
        "time": NoSleep,
    }
    helper_module = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(helper_module)
    exec(compile(helper_module, "main_multi_symbol.py", "exec"), namespace)
    return namespace


class FakeExchange:
    def __init__(self, order_status=None, fetch_order_error=None, create_limit_error=None):
        self.order_status = order_status or {"status": "open"}
        self.fetch_order_error = fetch_order_error
        self.create_limit_error = create_limit_error
        self.limit_buys = []
        self.limit_sells = []
        self.market_buys = []
        self.market_sells = []
        self.cancellations = []

    def fetch_ticker(self, _symbol):
        return {"last": 100.0}

    def create_limit_buy_order(self, symbol, amount, price):
        if self.create_limit_error:
            raise self.create_limit_error
        self.limit_buys.append((symbol, amount, price))
        return {"id": "limit-buy-1"}

    def create_limit_sell_order(self, symbol, amount, price):
        if self.create_limit_error:
            raise self.create_limit_error
        self.limit_sells.append((symbol, amount, price))
        return {"id": "limit-sell-1"}

    def fetch_order(self, _order_id, _symbol):
        if self.fetch_order_error:
            raise self.fetch_order_error
        return self.order_status

    def cancel_order(self, order_id, symbol):
        self.cancellations.append((order_id, symbol))
        return {"id": order_id, "status": "canceled"}

    def create_market_buy_order(self, symbol, cost):
        self.market_buys.append((symbol, cost))
        return {"id": "market-buy-1"}

    def create_market_sell_order(self, symbol, amount):
        self.market_sells.append((symbol, amount))
        return {"id": "market-sell-1"}

    def fetch_balance(self):
        return {"USD": {"free": 1000.0}}


class OrderSafetyTests(unittest.TestCase):
    def setUp(self):
        self.helpers = load_order_helpers()

    def test_unfilled_limit_entry_is_canceled_without_market_fallback(self):
        exchange = FakeExchange(order_status={"status": "open"})

        executed = self.helpers["place_entry_order"](
            exchange,
            "ETH/USD",
            "ETH",
            2.0,
            200.0,
            True,
            0.001,
            True,
        )

        self.assertIs(executed, False)
        self.assertEqual(exchange.cancellations, [("limit-buy-1", "ETH/USD")])
        self.assertEqual(exchange.market_buys, [])

    def test_uncertain_limit_entry_status_is_canceled_without_market_fallback(self):
        exchange = FakeExchange(fetch_order_error=RuntimeError("status unavailable"))

        executed = self.helpers["place_entry_order"](
            exchange,
            "ETH/USD",
            "ETH",
            2.0,
            200.0,
            True,
            0.001,
            True,
        )

        self.assertIs(executed, False)
        self.assertEqual(exchange.cancellations, [("limit-buy-1", "ETH/USD")])
        self.assertEqual(exchange.market_buys, [])

    def test_limit_create_failure_can_use_market_entry_fallback(self):
        exchange = FakeExchange(create_limit_error=RuntimeError("limit rejected"))

        executed = self.helpers["place_entry_order"](
            exchange,
            "ETH/USD",
            "ETH",
            2.0,
            200.0,
            True,
            0.001,
            True,
        )

        self.assertIs(executed, True)
        self.assertEqual(exchange.cancellations, [])
        self.assertEqual(exchange.market_buys, [("ETH/USD", 200.0)])

    def test_unfilled_limit_exit_is_canceled_without_market_fallback(self):
        exchange = FakeExchange(order_status={"status": "open"})

        executed = self.helpers["place_exit_order"](
            exchange,
            "ETH/USD",
            "ETH",
            2.0,
            "Profit-taking",
            True,
            0.001,
            True,
        )

        self.assertIs(executed, False)
        self.assertEqual(exchange.cancellations, [("limit-sell-1", "ETH/USD")])
        self.assertEqual(exchange.market_sells, [])

    def test_uncertain_limit_exit_status_is_canceled_without_market_fallback(self):
        exchange = FakeExchange(fetch_order_error=RuntimeError("status unavailable"))

        executed = self.helpers["place_exit_order"](
            exchange,
            "ETH/USD",
            "ETH",
            2.0,
            "Profit-taking",
            True,
            0.001,
            True,
        )

        self.assertIs(executed, False)
        self.assertEqual(exchange.cancellations, [("limit-sell-1", "ETH/USD")])
        self.assertEqual(exchange.market_sells, [])

    def test_position_size_cost_matches_recorded_base_amount(self):
        exchange = FakeExchange()

        amount, cost = self.helpers["get_position_size"](
            exchange,
            "ETH/USD",
            current_price=100.0,
            symbol_risk_slice=0.10,
            leverage=5,
        )

        self.assertEqual(amount, 5.0)
        self.assertEqual(cost, 500.0)
        self.assertEqual(amount * 100.0, cost)


if __name__ == "__main__":
    unittest.main()
