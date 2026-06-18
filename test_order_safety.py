import ast
import pathlib
import typing
import unittest


HELPER_NAMES = {
    "cancel_symbol_open_orders",
    "cancel_order_safely",
    "place_entry_order",
    "place_exit_order",
    "get_position_size",
}


class NoSleep:
    @staticmethod
    def sleep(_seconds):
        return None


def load_helpers():
    source_path = pathlib.Path(__file__).with_name("main_multi_symbol.py")
    tree = ast.parse(source_path.read_text())
    selected = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in HELPER_NAMES
    ]
    module = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"time": NoSleep, "Tuple": typing.Tuple}
    exec(compile(module, str(source_path), "exec"), namespace)
    return namespace


helpers = load_helpers()


class BalanceExchange:
    def fetch_balance(self):
        return {"USD": {"free": 1000.0}, "USDC": {"free": 0.0}}


class LimitEntryExchange:
    def __init__(self, status=None, fetch_order_exc=None):
        self.status = status or {"status": "open"}
        self.fetch_order_exc = fetch_order_exc
        self.canceled = []
        self.market_buys = []

    def fetch_ticker(self, _symbol):
        return {"last": 100.0}

    def fetch_open_orders(self, _symbol):
        return []

    def create_limit_buy_order(self, _symbol, _amount, _price):
        return {"id": "buy-1"}

    def fetch_order(self, _order_id, _symbol):
        if self.fetch_order_exc:
            raise self.fetch_order_exc
        return self.status

    def cancel_order(self, order_id, _symbol):
        self.canceled.append(order_id)

    def create_market_buy_order(self, _symbol, cost):
        self.market_buys.append(cost)
        return {"id": "market-buy-1"}


class LimitExitExchange:
    def __init__(self, open_orders=None, status=None):
        self.open_orders = open_orders if open_orders is not None else []
        self.status = status or {"status": "open"}
        self.canceled = []
        self.market_sells = []

    def fetch_ticker(self, _symbol):
        return {"last": 100.0}

    def fetch_open_orders(self, _symbol):
        return list(self.open_orders)

    def create_limit_sell_order(self, _symbol, _amount, _price):
        return {"id": "sell-1"}

    def fetch_order(self, _order_id, _symbol):
        return self.status

    def cancel_order(self, order_id, _symbol):
        self.canceled.append(order_id)

    def create_market_sell_order(self, _symbol, amount):
        self.market_sells.append(amount)
        return {"id": "market-sell-1"}


class OrderSafetyTests(unittest.TestCase):
    def test_position_cost_matches_recorded_amount(self):
        amount, cost = helpers["get_position_size"](
            BalanceExchange(),
            "BTC/USD",
            current_price=50000.0,
            symbol_risk_slice=0.10,
            leverage=5,
        )

        self.assertAlmostEqual(amount, 0.01)
        self.assertAlmostEqual(cost, 500.0)
        self.assertAlmostEqual(amount * 50000.0, cost)

    def test_unfilled_limit_entry_is_canceled_without_market_fallback(self):
        exchange = LimitEntryExchange(status={"status": "open"})

        executed = helpers["place_entry_order"](
            exchange,
            "ETH/USD",
            "ETH",
            amount=2.0,
            cost=200.0,
            use_limit_orders=True,
            limit_order_offset_pct=0.01,
            enable_trading=True,
        )

        self.assertFalse(executed)
        self.assertEqual(exchange.canceled, ["buy-1"])
        self.assertEqual(exchange.market_buys, [])

    def test_uncertain_limit_entry_is_canceled_without_market_fallback(self):
        exchange = LimitEntryExchange(fetch_order_exc=TimeoutError("status timeout"))

        executed = helpers["place_entry_order"](
            exchange,
            "ETH/USD",
            "ETH",
            amount=2.0,
            cost=200.0,
            use_limit_orders=True,
            limit_order_offset_pct=0.01,
            enable_trading=True,
        )

        self.assertFalse(executed)
        self.assertEqual(exchange.canceled, ["buy-1"])
        self.assertEqual(exchange.market_buys, [])

    def test_unfilled_limit_exit_is_canceled_without_market_fallback(self):
        exchange = LimitExitExchange(status={"status": "open"})

        executed = helpers["place_exit_order"](
            exchange,
            "ETH/USD",
            "ETH",
            amount=2.0,
            reason="Profit-taking",
            use_limit_orders=True,
            limit_order_offset_pct=0.01,
            enable_trading=True,
        )

        self.assertFalse(executed)
        self.assertEqual(exchange.canceled, ["sell-1"])
        self.assertEqual(exchange.market_sells, [])

    def test_forced_market_exit_clears_stale_limit_sells_first(self):
        exchange = LimitExitExchange(open_orders=[{"id": "old-sell", "side": "sell"}])

        executed = helpers["place_exit_order"](
            exchange,
            "ETH/USD",
            "ETH",
            amount=2.0,
            reason="Stop-loss",
            use_limit_orders=True,
            limit_order_offset_pct=0.01,
            enable_trading=True,
            force_market=True,
        )

        self.assertTrue(executed)
        self.assertEqual(exchange.canceled, ["old-sell"])
        self.assertEqual(exchange.market_sells, [2.0])


if __name__ == "__main__":
    unittest.main()
