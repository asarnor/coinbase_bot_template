import ast
import pathlib
import time
import unittest
from typing import Tuple
from unittest import mock


def load_order_helpers():
    source_path = pathlib.Path(__file__).with_name("main_multi_symbol.py")
    module_ast = ast.parse(source_path.read_text())
    wanted = {
        "cancel_unfilled_limit_order",
        "place_entry_order",
        "place_exit_order",
        "get_position_size",
    }
    helper_nodes = [
        node
        for node in module_ast.body
        if isinstance(node, ast.FunctionDef) and node.name in wanted
    ]
    compiled = compile(ast.Module(body=helper_nodes, type_ignores=[]), str(source_path), "exec")
    namespace = {"time": time, "Tuple": Tuple}
    exec(compiled, namespace)
    return namespace


HELPERS = load_order_helpers()
get_position_size = HELPERS["get_position_size"]
place_entry_order = HELPERS["place_entry_order"]
place_exit_order = HELPERS["place_exit_order"]


class OrderSafetyTest(unittest.TestCase):
    def test_position_cost_matches_leveraged_amount_value(self):
        exchange = mock.Mock()
        exchange.fetch_balance.return_value = {"USD": {"free": 1000.0}}

        amount, cost = get_position_size(
            exchange,
            symbol="ETH/USD",
            current_price=100.0,
            symbol_risk_slice=0.20,
            leverage=5,
        )

        self.assertEqual(amount, 10.0)
        self.assertEqual(cost, 1000.0)
        self.assertEqual(amount * 100.0, cost)

    def test_unfilled_limit_entry_is_canceled_without_market_fallback(self):
        exchange = mock.Mock()
        exchange.fetch_ticker.return_value = {"last": 100.0}
        exchange.create_limit_buy_order.return_value = {"id": "buy-1"}
        exchange.fetch_order.return_value = {"status": "open"}

        with mock.patch.object(HELPERS["time"], "sleep"):
            executed = place_entry_order(
                exchange,
                "ETH/USD",
                "ETH",
                amount=10.0,
                cost=1000.0,
                use_limit_orders=True,
                limit_order_offset_pct=0.001,
                enable_trading=True,
            )

        self.assertFalse(executed)
        exchange.cancel_order.assert_called_once_with("buy-1", "ETH/USD")
        exchange.create_market_buy_order.assert_not_called()

    def test_uncertain_limit_entry_status_is_canceled_without_market_fallback(self):
        exchange = mock.Mock()
        exchange.fetch_ticker.return_value = {"last": 100.0}
        exchange.create_limit_buy_order.return_value = {"id": "buy-1"}
        exchange.fetch_order.side_effect = RuntimeError("status timeout")

        with mock.patch.object(HELPERS["time"], "sleep"):
            executed = place_entry_order(
                exchange,
                "ETH/USD",
                "ETH",
                amount=10.0,
                cost=1000.0,
                use_limit_orders=True,
                limit_order_offset_pct=0.001,
                enable_trading=True,
            )

        self.assertFalse(executed)
        exchange.cancel_order.assert_called_once_with("buy-1", "ETH/USD")
        exchange.create_market_buy_order.assert_not_called()

    def test_unfilled_limit_exit_is_canceled_without_market_fallback(self):
        exchange = mock.Mock()
        exchange.fetch_ticker.return_value = {"last": 100.0}
        exchange.create_limit_sell_order.return_value = {"id": "sell-1"}
        exchange.fetch_order.return_value = {"status": "open"}

        with mock.patch.object(HELPERS["time"], "sleep"):
            executed = place_exit_order(
                exchange,
                "ETH/USD",
                "ETH",
                amount=10.0,
                reason="Profit-taking",
                use_limit_orders=True,
                limit_order_offset_pct=0.001,
                enable_trading=True,
            )

        self.assertFalse(executed)
        exchange.cancel_order.assert_called_once_with("sell-1", "ETH/USD")
        exchange.create_market_sell_order.assert_not_called()

    def test_uncertain_limit_exit_status_is_canceled_without_market_fallback(self):
        exchange = mock.Mock()
        exchange.fetch_ticker.return_value = {"last": 100.0}
        exchange.create_limit_sell_order.return_value = {"id": "sell-1"}
        exchange.fetch_order.side_effect = RuntimeError("status timeout")

        with mock.patch.object(HELPERS["time"], "sleep"):
            executed = place_exit_order(
                exchange,
                "ETH/USD",
                "ETH",
                amount=10.0,
                reason="Profit-taking",
                use_limit_orders=True,
                limit_order_offset_pct=0.001,
                enable_trading=True,
            )

        self.assertFalse(executed)
        exchange.cancel_order.assert_called_once_with("sell-1", "ETH/USD")
        exchange.create_market_sell_order.assert_not_called()


if __name__ == "__main__":
    unittest.main()
