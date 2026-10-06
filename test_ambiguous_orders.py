#!/usr/bin/env python3
"""Ambiguous order failures must halt further live orders.

Importing the bots starts their trading loops, so this test inspects source ASTs.
"""
import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def _call_names(tree: ast.AST) -> set:
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


def _handlers_for_order_call(tree: ast.AST, order_method: str):
    handlers = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        places_order = any(
            isinstance(child, ast.Attribute) and child.attr == order_method
            for statement in node.body
            for child in ast.walk(statement)
        )
        if places_order:
            handlers.extend(node.handlers)
    return handlers


class AmbiguousOrderHaltTests(unittest.TestCase):
    def test_multi_symbol_market_orders_classify_and_halt(self):
        tree = ast.parse((ROOT / "main_multi_symbol.py").read_text(encoding="utf-8"))
        calls = _call_names(tree)
        self.assertIn("order_failure_is_ambiguous", calls)
        self.assertIn("halt_symbol_orders", calls)

        for order_method in ("create_market_buy_order", "create_market_sell_order"):
            handlers = _handlers_for_order_call(tree, order_method)
            self.assertGreaterEqual(len(handlers), 1, order_method)
            self.assertTrue(
                any("order_failure_is_ambiguous" in _call_names(handler) for handler in handlers),
                f"{order_method} failure must be classified before another order is sent",
            )

    def test_legacy_main_halts_entries_after_ambiguous_buy(self):
        tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
        buy_handlers = _handlers_for_order_call(tree, "create_market_buy_order")
        live_handlers = []
        for handler in buy_handlers:
            assigned = [
                target.id
                for node in ast.walk(handler)
                if isinstance(node, ast.Assign)
                for target in node.targets
                if isinstance(target, ast.Name)
            ]
            if "entry_halted" in assigned and "order_failure_is_ambiguous" in _call_names(handler):
                live_handlers.append(handler)
        self.assertEqual(
            len(live_handlers),
            1,
            "the live buy loop must halt entries when the order result is ambiguous",
        )

        buy_guard_found = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            condition = ast.dump(node.test)
            if "entry_halted" in condition and "in_position" in condition:
                buy_guard_found = True
                break
        self.assertTrue(buy_guard_found, "new buys must be skipped once entry_halted is set")


if __name__ == "__main__":
    unittest.main()
