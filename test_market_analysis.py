#!/usr/bin/env python3
"""Regression tests for closed-candle entries and current-price exits."""
import ast
from pathlib import Path
import unittest

import pandas as pd


def load_function(name):
    source_path = Path(__file__).with_name("main_multi_symbol.py")
    tree = ast.parse(source_path.read_text())
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )
    namespace = {"pd": pd}
    exec(compile(ast.Module(body=[function], type_ignores=[]), source_path, "exec"), namespace)
    return namespace[name]


select_evaluation_price = load_function("select_evaluation_price")


class EvaluationPriceTests(unittest.TestCase):
    def setUp(self):
        self.prices = pd.DataFrame({"close": [100.0, 90.0]})
        self.closed_signal = self.prices.iloc[-2]

    def test_flat_position_uses_closed_candle_price(self):
        self.assertEqual(
            select_evaluation_price(self.prices, self.closed_signal, False),
            100.0,
        )

    def test_open_position_uses_latest_price(self):
        self.assertEqual(
            select_evaluation_price(self.prices, self.closed_signal, True),
            90.0,
        )


if __name__ == "__main__":
    unittest.main()
