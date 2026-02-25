#!/usr/bin/env python3
import unittest

import numpy as np
import pandas as pd

from strategy_validation import backtest_symbol


def build_ohlcv(closes: np.ndarray) -> pd.DataFrame:
    n = len(closes)
    timestamps = np.arange(n) * 3600_000
    opens = closes * 0.999
    highs = closes * 1.01
    lows = closes * 0.99
    volumes = 1_000 + (np.arange(n) % 10) * 25
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        }
    )


class StrategyValidationTests(unittest.TestCase):
    def test_uptrend_scores_better_than_downtrend(self) -> None:
        uptrend_closes = np.linspace(100, 220, 320) + np.sin(np.linspace(0, 15, 320)) * 1.2
        downtrend_closes = np.linspace(220, 80, 320) + np.sin(np.linspace(0, 20, 320)) * 2.0

        up_result = backtest_symbol(build_ohlcv(uptrend_closes), "UP/USD")
        down_result = backtest_symbol(build_ohlcv(downtrend_closes), "DOWN/USD")

        self.assertGreater(up_result.score, down_result.score)
        self.assertEqual(down_result.recommendation, "SELL")
        self.assertLess(down_result.score, 60.0)

    def test_short_history_returns_safe_keep(self) -> None:
        short_closes = np.linspace(100, 110, 60)
        result = backtest_symbol(build_ohlcv(short_closes), "SHORT/USD")

        self.assertEqual(result.recommendation, "KEEP")
        self.assertIn("Not enough historical data", result.reason)
        self.assertEqual(result.trades, 0)


if __name__ == "__main__":
    unittest.main()
