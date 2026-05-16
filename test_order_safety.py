import ast
import types
import unittest
from pathlib import Path
from typing import Dict, List, Tuple


def load_bot_functions(*function_names):
    source_path = Path(__file__).with_name("main_multi_symbol.py")
    module = ast.parse(source_path.read_text())
    selected_nodes = [
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name in function_names
    ]
    loaded_names = {node.name for node in selected_nodes}
    missing_names = set(function_names) - loaded_names
    if missing_names:
        raise AssertionError(f"Missing functions: {sorted(missing_names)}")

    namespace = {
        "Dict": Dict,
        "List": List,
        "Tuple": Tuple,
        "time": types.SimpleNamespace(sleep=lambda seconds: None),
    }
    compiled = compile(
        ast.Module(body=selected_nodes, type_ignores=[]),
        filename=str(source_path),
        mode="exec",
    )
    exec(compiled, namespace)
    return {name: namespace[name] for name in function_names}


FUNCTIONS = load_bot_functions("get_position_size", "place_entry_order", "place_exit_order")
get_position_size = FUNCTIONS["get_position_size"]
place_entry_order = FUNCTIONS["place_entry_order"]
place_exit_order = FUNCTIONS["place_exit_order"]


class BalanceExchange:
    def __init__(self, free_usd):
        self.free_usd = free_usd

    def fetch_balance(self):
        return {"USD": {"free": self.free_usd}, "USDC": {"free": 0}}


class OpenLimitExchange:
    def __init__(self):
        self.canceled_orders = []
        self.market_buys = []
        self.market_sells = []

    def fetch_ticker(self, symbol):
        return {"last": 100}

    def create_limit_buy_order(self, symbol, amount, limit_price):
        self.limit_buy = (symbol, amount, limit_price)
        return {"id": "entry-1"}

    def create_limit_sell_order(self, symbol, amount, limit_price):
        self.limit_sell = (symbol, amount, limit_price)
        return {"id": "exit-1"}

    def fetch_order(self, order_id, symbol):
        return {"id": order_id, "status": "open"}

    def cancel_order(self, order_id, symbol):
        self.canceled_orders.append((order_id, symbol))
        return {"id": order_id, "status": "canceled"}

    def create_market_buy_order(self, symbol, cost):
        self.market_buys.append((symbol, cost))
        raise AssertionError("market buy should not run while a limit buy is open")

    def create_market_sell_order(self, symbol, amount):
        self.market_sells.append((symbol, amount))
        raise AssertionError("market sell should not run while a limit sell is open")


class OrderSafetyTests(unittest.TestCase):
    def test_position_size_cost_matches_recorded_base_amount(self):
        amount, cost = get_position_size(
            BalanceExchange(free_usd=1000),
            "ETH/USD",
            current_price=100,
            symbol_risk_slice=0.20,
            leverage=5,
        )

        self.assertEqual(cost, 1000)
        self.assertEqual(amount, 10)
        self.assertEqual(amount * 100, cost)

    def test_unfilled_limit_entry_is_canceled_before_retry(self):
        exchange = OpenLimitExchange()

        executed = place_entry_order(
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
        self.assertEqual(exchange.canceled_orders, [("entry-1", "ETH/USD")])
        self.assertEqual(exchange.market_buys, [])

    def test_unfilled_limit_exit_is_canceled_before_retry(self):
        exchange = OpenLimitExchange()

        executed = place_exit_order(
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
        self.assertEqual(exchange.canceled_orders, [("exit-1", "ETH/USD")])
        self.assertEqual(exchange.market_sells, [])


if __name__ == "__main__":
    unittest.main()
