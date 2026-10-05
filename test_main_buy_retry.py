#!/usr/bin/env python3
"""A failed live buy in main.py must wait before the next attempt.

Importing main.py starts the trading loop, so this test inspects the source AST.
"""
import ast
import unittest
from pathlib import Path


SOURCE_PATH = Path(__file__).with_name("main.py")


def _is_sleep_call(statement: ast.stmt) -> bool:
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Call)
        and isinstance(statement.value.func, ast.Attribute)
        and statement.value.func.attr == "sleep"
    )


class BuyRetryBackoffTests(unittest.TestCase):
    def test_failed_market_buy_sleeps_before_continue(self):
        tree = ast.parse(SOURCE_PATH.read_text(encoding="utf-8"))
        retry_handlers = []

        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            places_market_buy = any(
                isinstance(child, ast.Attribute) and child.attr == "create_market_buy_order"
                for statement in node.body
                for child in ast.walk(statement)
            )
            if not places_market_buy:
                continue
            for handler in node.handlers:
                if any(isinstance(statement, ast.Continue) for statement in handler.body):
                    retry_handlers.append(handler)

        self.assertEqual(len(retry_handlers), 1)
        handler = retry_handlers[0]
        sleep_at = None
        continue_at = None
        for index, statement in enumerate(handler.body):
            if _is_sleep_call(statement):
                sleep_at = index
            if isinstance(statement, ast.Continue):
                continue_at = index

        self.assertIsNotNone(sleep_at, "failed buy handler must sleep before retrying")
        self.assertIsNotNone(continue_at)
        self.assertLess(sleep_at, continue_at)


if __name__ == "__main__":
    unittest.main()
