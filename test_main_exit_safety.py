#!/usr/bin/env python3
"""Regression tests for the legacy bot's stop-loss order handling."""
import ast
import pathlib
import unittest


SOURCE_PATH = pathlib.Path(__file__).with_name("main.py")


def load_place_exit_order():
    tree = ast.parse(SOURCE_PATH.read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "place_exit_order"
    )
    namespace = {}
    module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    exec(compile(module, str(SOURCE_PATH), "exec"), namespace)
    return namespace["place_exit_order"]


class FakeExchange:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def create_market_sell_order(self, symbol, amount):
        self.calls.append((symbol, amount))
        if self.error:
            raise self.error
        return {"id": "sell-123"}


class PlaceExitOrderTests(unittest.TestCase):
    def setUp(self):
        self.place_exit_order = load_place_exit_order()

    def test_successful_live_sell_allows_position_reset(self):
        exchange = FakeExchange()

        result = self.place_exit_order(exchange, "ETH/USD", 1.25, True)

        self.assertTrue(result)
        self.assertEqual(exchange.calls, [("ETH/USD", 1.25)])

    def test_failed_live_sell_keeps_position_open_for_retry(self):
        exchange = FakeExchange(RuntimeError("temporary exchange outage"))

        result = self.place_exit_order(exchange, "ETH/USD", 1.25, True)

        self.assertFalse(result)
        self.assertEqual(exchange.calls, [("ETH/USD", 1.25)])

    def test_simulation_completes_without_submitting_an_order(self):
        exchange = FakeExchange()

        result = self.place_exit_order(exchange, "ETH/USD", 1.25, False)

        self.assertTrue(result)
        self.assertEqual(exchange.calls, [])

    def test_position_reset_is_guarded_by_successful_sell(self):
        tree = ast.parse(SOURCE_PATH.read_text(encoding="utf-8"))
        guarded_resets = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.If) or not isinstance(node.test, ast.Call):
                continue
            if not isinstance(node.test.func, ast.Name) or node.test.func.id != "place_exit_order":
                continue
            assignments = {
                target.id
                for statement in node.body
                if isinstance(statement, ast.Assign)
                for target in statement.targets
                if isinstance(target, ast.Name)
            }
            guarded_resets.append(assignments)

        self.assertEqual(len(guarded_resets), 1)
        self.assertTrue(
            {"in_position", "trailing_stop_price", "position_amount"}.issubset(
                guarded_resets[0]
            )
        )


if __name__ == "__main__":
    unittest.main()
