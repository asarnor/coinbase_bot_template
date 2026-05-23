#!/usr/bin/env python3
import ast
import pathlib
import unittest


HELPER_NAMES = {
    "order_filled_amount",
    "cancel_order_safely",
    "get_position_size",
    "place_entry_order",
    "place_exit_order",
}


def load_order_helpers():
    source_path = pathlib.Path(__file__).with_name("main_multi_symbol.py")
    tree = ast.parse(source_path.read_text())
    body = [
        ast.Import(names=[ast.alias(name="time")]),
        ast.ImportFrom(
            module="typing",
            names=[ast.alias(name="Dict"), ast.alias(name="Tuple")],
            level=0,
        ),
    ]
    body.extend(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in HELPER_NAMES
    )
    module = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(module)

    namespace = {}
    exec(compile(module, str(source_path), "exec"), namespace)
    namespace["time"].sleep = lambda _: None
    return namespace


class BalanceExchange:
    def fetch_balance(self):
        return {"USD": {"free": 1000.0}}


class LimitExchange:
    def __init__(self, order_status):
        self.order_status = order_status
        self.cancelled_orders = []

    def fetch_ticker(self, symbol):
        return {"last": 100.0}

    def create_limit_buy_order(self, symbol, amount, price):
        self.buy_order = {"symbol": symbol, "amount": amount, "price": price}
        return {"id": "buy-1"}

    def create_limit_sell_order(self, symbol, amount, price):
        self.sell_order = {"symbol": symbol, "amount": amount, "price": price}
        return {"id": "sell-1"}

    def fetch_order(self, order_id, symbol):
        return self.order_status

    def cancel_order(self, order_id, symbol):
        self.cancelled_orders.append((order_id, symbol))


class MarketBuyExchange:
    def __init__(self):
        self.market_buy = None

    def create_market_buy_order(self, symbol, cost):
        self.market_buy = {"symbol": symbol, "cost": cost}
        return {"id": "market-buy-1", "filled": 5.0}


class OrderSafetyTests(unittest.TestCase):
    def setUp(self):
        self.helpers = load_order_helpers()

    def test_position_size_cost_matches_recorded_base_amount(self):
        amount, cost = self.helpers["get_position_size"](
            BalanceExchange(),
            "ETH/USD",
            current_price=100.0,
            symbol_risk_slice=0.10,
            leverage=5,
        )

        self.assertEqual(amount, 5.0)
        self.assertEqual(cost, 500.0)
        self.assertEqual(amount * 100.0, cost)

    def test_market_entry_returns_actual_filled_amount(self):
        exchange = MarketBuyExchange()

        executed, filled_amount = self.helpers["place_entry_order"](
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
        self.assertEqual(filled_amount, 5.0)
        self.assertEqual(exchange.market_buy, {"symbol": "ETH/USD", "cost": 500.0})

    def test_unfilled_limit_entry_is_canceled(self):
        exchange = LimitExchange({"id": "buy-1", "status": "open", "filled": 0})

        executed, filled_amount = self.helpers["place_entry_order"](
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
        self.assertEqual(exchange.cancelled_orders, [("buy-1", "ETH/USD")])

    def test_partial_limit_exit_is_canceled_and_reported(self):
        exchange = LimitExchange({"id": "sell-1", "status": "open", "filled": 1.25})

        executed, filled_amount = self.helpers["place_exit_order"](
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
        self.assertEqual(filled_amount, 1.25)
        self.assertEqual(exchange.cancelled_orders, [("sell-1", "ETH/USD")])


if __name__ == "__main__":
    unittest.main()
