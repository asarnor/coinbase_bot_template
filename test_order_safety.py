import ast
import types
import unittest
from pathlib import Path


HELPER_NAMES = {
    "reset_position_state",
    "get_order_filled_amount",
    "cancel_stale_limit_order",
    "apply_exit_fill",
    "get_position_size",
    "place_entry_order",
    "place_exit_order",
}


def load_bot_helpers():
    source = Path("main_multi_symbol.py").read_text()
    module = ast.parse(source)
    helper_nodes = [
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name in HELPER_NAMES
    ]
    namespace = {
        "Dict": dict,
        "Tuple": tuple,
        "time": types.SimpleNamespace(time=lambda: 123456.0, sleep=lambda _seconds: None),
    }
    compiled = ast.Module(body=helper_nodes, type_ignores=[])
    ast.fix_missing_locations(compiled)
    exec(compile(compiled, "main_multi_symbol.py", "exec"), namespace)
    return namespace


helpers = load_bot_helpers()


class BalanceExchange:
    def __init__(self, balance):
        self.balance = balance

    def fetch_balance(self):
        return self.balance


class LimitExchange:
    def __init__(self, order_status):
        self.order_status = order_status
        self.canceled_orders = []
        self.market_buys = []
        self.market_sells = []

    def fetch_ticker(self, _symbol):
        return {"last": 100.0}

    def create_limit_buy_order(self, _symbol, _amount, _limit_price):
        return {"id": "limit-buy-1"}

    def create_limit_sell_order(self, _symbol, _amount, _limit_price):
        return {"id": "limit-sell-1"}

    def fetch_order(self, _order_id, _symbol):
        return self.order_status

    def cancel_order(self, order_id, _symbol):
        self.canceled_orders.append(order_id)

    def create_market_buy_order(self, symbol, cost):
        self.market_buys.append((symbol, cost))
        return {"id": "market-buy-1", "filled": cost / 100.0}

    def create_market_sell_order(self, symbol, amount):
        self.market_sells.append((symbol, amount))
        return {"id": "market-sell-1", "filled": amount}


class OrderSafetyTests(unittest.TestCase):
    def test_position_size_quote_cost_matches_amount_times_price(self):
        exchange = BalanceExchange({"USD": {"free": 1000.0}})

        amount, cost = helpers["get_position_size"](
            exchange,
            "ETH/USD",
            current_price=100.0,
            symbol_risk_slice=0.2,
            leverage=5,
        )

        self.assertEqual(cost, 1000.0)
        self.assertEqual(amount, 10.0)
        self.assertEqual(amount * 100.0, cost)

    def test_spot_sizing_uses_effective_1x_leverage(self):
        exchange = BalanceExchange({"USD": {"free": 1000.0}})

        amount, cost = helpers["get_position_size"](
            exchange,
            "ETH/USD",
            current_price=100.0,
            symbol_risk_slice=0.2,
            leverage=1,
        )

        self.assertEqual(cost, 200.0)
        self.assertEqual(amount, 2.0)

    def test_market_entry_returns_actual_filled_amount(self):
        exchange = LimitExchange(order_status={})

        executed, filled_amount = helpers["place_entry_order"](
            exchange,
            "ETH/USD",
            "ETH",
            amount=2.0,
            cost=200.0,
            use_limit_orders=False,
            limit_order_offset_pct=0.001,
            enable_trading=True,
        )

        self.assertTrue(executed)
        self.assertEqual(filled_amount, 2.0)
        self.assertEqual(exchange.market_buys, [("ETH/USD", 200.0)])

    def test_unfilled_limit_entry_is_canceled_without_market_fallback(self):
        exchange = LimitExchange(order_status={"status": "open", "filled": 0})

        executed, filled_amount = helpers["place_entry_order"](
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
        self.assertEqual(exchange.canceled_orders, ["limit-buy-1"])
        self.assertEqual(exchange.market_buys, [])

    def test_unfilled_limit_exit_is_canceled(self):
        exchange = LimitExchange(order_status={"status": "open", "filled": 0})

        executed, filled_amount = helpers["place_exit_order"](
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
        self.assertEqual(exchange.canceled_orders, ["limit-sell-1"])

    def test_partial_exit_reduces_tracked_position_amount(self):
        position = {
            "in_position": True,
            "position_amount": 2.0,
            "entry_price": 100.0,
            "trailing_stop_price": 95.0,
            "peak_price": 105.0,
            "trailing_profit_target": 103.0,
            "breakeven_set": True,
            "last_exit_time": 0,
        }

        closed = helpers["apply_exit_fill"](position, 0.75, record_exit=True)

        self.assertFalse(closed)
        self.assertEqual(position["position_amount"], 1.25)
        self.assertTrue(position["in_position"])


if __name__ == "__main__":
    unittest.main()
