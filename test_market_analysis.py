#!/usr/bin/env python3
"""Regression tests for market row selection in main_multi_symbol.

The bot starts its infinite loop at import time, so these tests load only the
helper function under test from the AST.
"""
import ast
import unittest
from pathlib import Path

import pandas as pd


class FakeTA:
    @staticmethod
    def ema(close, length):
        return close

    @staticmethod
    def rsi(close, length):
        return close * 0 + 50

    @staticmethod
    def atr(high, low, close, length):
        return high - low


def load_analyze_market():
    tree = ast.parse(Path("main_multi_symbol.py").read_text())
    selected = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "analyze_market"
    ]
    module = ast.Module(body=selected, type_ignores=[])
    namespace = {"pd": pd, "ta": FakeTA}
    exec(compile(ast.fix_missing_locations(module), "main_multi_symbol_analyze", "exec"), namespace)
    return namespace["analyze_market"]


analyze_market = load_analyze_market()


def sample_df(rows=30):
    values = list(range(100, 100 + rows))
    return pd.DataFrame(
        {
            "timestamp": list(range(rows)),
            "open": values,
            "high": [value + 1 for value in values],
            "low": [value - 1 for value in values],
            "close": values,
            "volume": [1000 + value for value in values],
        }
    )


class AnalyzeMarketRowSelectionTests(unittest.TestCase):
    def test_default_uses_last_closed_candle_for_entry_signals(self):
        row = analyze_market(sample_df())
        self.assertEqual(row["close"], 128)

    def test_live_mode_uses_latest_price_for_exit_checks(self):
        row = analyze_market(sample_df(), use_closed_candle=False)
        self.assertEqual(row["close"], 129)

    def test_single_row_is_available_in_closed_candle_mode(self):
        row = analyze_market(sample_df(rows=1))
        self.assertEqual(row["close"], 100)


if __name__ == "__main__":
    unittest.main()
